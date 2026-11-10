--[[
  BridgeCore.lua —— Lightroom Classic ↔ 外部程序 的文件队列桥

  为什么用文件队列：Lightroom 插件运行在受限的 Lua 沙箱里，
  但 io / LrFileUtils 可用，因此「收命令 → 执行 → 回结果」最稳。

  目录结构（必须是纯 ASCII 路径，Lua 的 io 打不开中文路径）：
    <ROOT>/inbox    外部写入 <id>.cmd
    <ROOT>/outbox   插件写回 <id>.res
    <ROOT>/plugin.log / heartbeat.txt

  ROOT 解析顺序：环境变量 LR_BRIDGE_ROOT > 用户主目录下的 lr_bridge
  （Python 端 lr_bridge.py 的 _resolve_root() 用同一套规则，两端必须一致。）

  协议：每行 key|type|value，type ∈ s / i / f / b / a
  值内的 \ | 换行 会被转义，安全。
]]

local LrApplication = import 'LrApplication'
local LrTasks = import 'LrTasks'
local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrExportSession = import 'LrExportSession'

local M = {}

local VERSION = '1.0.0'

-- 路径解析顺序（Python 端 lr_bridge.py 必须完全一致）：
--   1. 环境变量 LR_BRIDGE_ROOT
--   2. ~/lr_bridge（推荐，跨平台默认）
--   3. O:\lr_bridge（兼容早期安装，仅当该目录已存在）
local function resolveRoot()
	local env = os.getenv('LR_BRIDGE_ROOT')
	if env and #env > 0 then
		return env
	end
	local home = LrPathUtils.getStandardFilePath('home')
	local preferred = nil
	if home and #home > 0 then
		preferred = LrPathUtils.child(home, 'lr_bridge')
		if LrFileUtils.exists(preferred) then
			return preferred
		end
	end
	local legacy = 'O:\\lr_bridge'
	if LrFileUtils.exists(legacy) then
		return legacy
	end
	return preferred or 'lr_bridge'
end

local ROOT    = resolveRoot()
local INBOX   = LrPathUtils.child(ROOT, 'inbox')
local OUTBOX  = LrPathUtils.child(ROOT, 'outbox')
local LOGF    = LrPathUtils.child(ROOT, 'plugin.log')
local HEART   = LrPathUtils.child(ROOT, 'heartbeat.txt')

M.running = false
M.gen = 0
M.ROOT = ROOT
M.VERSION = VERSION

-- ---------------------------------------------------------------- 基础工具

local function esc(s)
	s = tostring(s)
	s = string.gsub(s, '\\', '\\\\')
	s = string.gsub(s, '|', '\\|')
	s = string.gsub(s, '\r', '\\r')
	s = string.gsub(s, '\n', '\\n')
	return s
end

local function unesc(s)
	local out, i, n = {}, 1, #s
	while i <= n do
		local c = string.sub(s, i, i)
		if c == '\\' and i < n then
			local d = string.sub(s, i + 1, i + 1)
			if d == 'n' then out[#out + 1] = '\n'
			elseif d == 'r' then out[#out + 1] = '\r'
			elseif d == 't' then out[#out + 1] = '\t'
			else out[#out + 1] = d end
			i = i + 2
		else
			out[#out + 1] = c
			i = i + 1
		end
	end
	return table.concat(out)
end

local function split3(line)
	local fields, cur = {}, {}
	local i, n = 1, #line
	while i <= n do
		local c = string.sub(line, i, i)
		if c == '\\' and i < n then
			cur[#cur + 1] = string.sub(line, i, i + 1)
			i = i + 2
		elseif c == '|' then
			fields[#fields + 1] = table.concat(cur)
			cur = {}
			i = i + 1
		else
			cur[#cur + 1] = c
			i = i + 1
		end
	end
	fields[#fields + 1] = table.concat(cur)
	return fields
end

local HASIO = (io ~= nil)

local function readFile(p)
	if not HASIO then return nil end
	local f = io.open(p, 'rb')
	if not f then return nil end
	local s = f:read('*a')
	f:close()
	return s
end

local function writeFile(p, s)
	if not HASIO then return false end
	local f = io.open(p, 'wb')
	if not f then return false end
	f:write(s)
	f:close()
	return true
end

function M.log(msg)
	if not HASIO then return end
	LrTasks.pcall(function()
		LrFileUtils.createAllDirectories(ROOT)
		local f = io.open(LOGF, 'a')
		if f then
			f:write(os.date('%Y-%m-%d %H:%M:%S') .. ' ' .. tostring(msg) .. '\n')
			f:close()
		end
	end)
end

-- ---------------------------------------------------------------- 命令对象

local Cmd = {}
Cmd.__index = Cmd

function Cmd.new()
	return setmetatable({ fields = {}, order = {} }, Cmd)
end

function Cmd:put(key, val)
	self.fields[key] = val
	if self.fields[key] == nil then self.fields[key] = false end
	self.order[#self.order + 1] = key
end

function Cmd:get(key, default)
	local v = self.fields[key]
	if v == nil then return default end
	return v
end

function Cmd:listOf(prefix)
	local out = {}
	for _, k in ipairs(self.order) do
		if k == prefix or string.sub(k, 1, #prefix + 1) == prefix .. '.' then
			out[#out + 1] = self.fields[k]
		end
	end
	return out
end

local function parseCmd(text)
	local cmd = Cmd.new()
	for raw in string.gmatch(text .. '\n', '([^\n]*)\n') do
		local line = string.gsub(raw, '\r$', '')
		if line ~= '' and string.sub(line, 1, 1) ~= '#' then
			local f = split3(line)
			local key = unesc(f[1] or '')
			local typ = f[2] or 's'
			local raw = unesc(f[3] or '')
			local val
			if typ == 'i' then val = tonumber(raw) or 0
			elseif typ == 'f' then val = tonumber(raw) or 0
			elseif typ == 'b' then val = (raw == '1' or raw == 'true')
			elseif typ == 'a' then
				val = {}
				for item in string.gmatch(raw .. ',', '([^,]*),') do
					val[#val + 1] = tonumber(item) or 0
				end
			else val = raw end
			if key ~= '' then cmd:put(key, val) end
		end
	end
	return cmd
end

-- ---------------------------------------------------------------- 结果对象

local Res = {}
Res.__index = Res

function Res.new() return setmetatable({ lines = {} }, Res) end

function Res:put(key, typ, val)
	local s
	if typ == 'b' then s = val and '1' or '0'
	elseif typ == 'i' then s = string.format('%d', math.floor(tonumber(val) or 0))
	elseif typ == 'f' then s = string.format('%.6g', tonumber(val) or 0)
	elseif typ == 'a' then
		local parts = {}
		for _, v in ipairs(val or {}) do parts[#parts + 1] = string.format('%.6g', tonumber(v) or 0) end
		s = table.concat(parts, ',')
	else s = tostring(val == nil and '' or val) end
	self.lines[#self.lines + 1] = esc(key) .. '|' .. typ .. '|' .. esc(s)
end

function Res:text()
	return table.concat(self.lines, '\n') .. '\n'
end

-- ---------------------------------------------------------------- 业务辅助

local function catalogOrError()
	local c = LrApplication.activeCatalog()
	if not c then error('Lightroom 没有打开目录') end
	return c
end

local function resolvePhotos(cmd)
	local catalog = catalogOrError()
	local paths = cmd:listOf('path')
	if #paths == 0 then
		return catalog:getTargetPhotos() or {}, catalog
	end
	local out, missing = {}, {}
	for _, p in ipairs(paths) do
		local photo = catalog:findPhotoByPath(p)
		if photo then out[#out + 1] = photo else missing[#missing + 1] = p end
	end
	return out, catalog, missing
end

local function photoField(photo, fn, default)
	local ok, v = LrTasks.pcall(fn, photo)
	if ok then return v end
	return default
end

-- 把嵌套表展平成 a.b.1.c 形式，用于诊断/读取复杂结构（如蒙版）
local function flatten(v, prefix, out, depth)
	depth = depth or 0
	local t = type(v)
	if depth > 8 then return end
	if t == 'table' then
		local n, count = #v, 0
		for _ in pairs(v) do count = count + 1 end
		if n > 0 and count == n then
			for i = 1, n do flatten(v[i], prefix .. '.' .. i, out, depth + 1) end
		else
			local keys = {}
			for k in pairs(v) do keys[#keys + 1] = k end
			table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
			for _, k in ipairs(keys) do flatten(v[k], prefix .. '.' .. tostring(k), out, depth + 1) end
		end
	elseif t == 'number' then out[#out + 1] = { prefix, 'f', v }
	elseif t == 'boolean' then out[#out + 1] = { prefix, 'b', v }
	elseif t == 'string' then out[#out + 1] = { prefix, 's', v }
	end
end

local function describePhoto(photo, idx, res)
	local prefix = 'p' .. idx .. '.'
	local path = photoField(photo, function(p) return p:getRawMetadata('path') end, '')
	res:put(prefix .. 'path', 's', path)
	res:put(prefix .. 'name', 's', path ~= '' and LrPathUtils.leafName(path) or '')
	res:put(prefix .. 'rating', 'i', photoField(photo, function(p) return p:getRawMetadata('rating') end, 0))
	res:put(prefix .. 'label', 's', photoField(photo, function(p) return p:getRawMetadata('colorNameForLabel') end, ''))
	res:put(prefix .. 'format', 's', photoField(photo, function(p) return p:getRawMetadata('fileFormat') end, ''))
	res:put(prefix .. 'vc', 'b', photoField(photo, function(p) return p:getRawMetadata('isVirtualCopy') end, false))
	local kws = photoField(photo, function(p) return p:getRawMetadata('keywords') end, {}) or {}
	res:put(prefix .. 'keywords', 's', table.concat(kws, ';'))
	local okd, a, b = LrTasks.pcall(function() return photo:getRawMetadata('dimensions') end)
	if okd then
		local w, h
		if type(a) == 'table' then
			w, h = a.width or a[1], a.height or a[2]
		else
			w, h = a, b
		end
		res:put(prefix .. 'w', 'i', w or 0)
		res:put(prefix .. 'h', 'i', h or 0)
	end
	res:put(prefix .. 'time', 's', photoField(photo, function(p) return p:getFormattedMetadata('dateTimeOriginal') end, ''))
end

-- ---------------------------------------------------------------- 操作实现

local OPS = {}

function OPS.ping(cmd, res)
	res:put('version', 's', VERSION)
	res:put('root', 's', ROOT)
	res:put('running', 'b', M.running)
	res:put('time', 's', os.date('%Y-%m-%d %H:%M:%S'))
	local c = LrApplication.activeCatalog()
	res:put('catalog', 's', c and c:getPath() or '')
end

function OPS.status(cmd, res)
	OPS.ping(cmd, res)
	local okm, mod = LrTasks.pcall(function()
		return import('LrApplicationView').getCurrentModuleName()
	end)
	res:put('module', 's', okm and tostring(mod) or '')
	local okc, c = LrTasks.pcall(LrApplication.activeCatalog)
	if okc and c then
		local photos = c:getTargetPhotos() or {}
		res:put('selected', 'i', #photos)
	end
end

function OPS.selection(cmd, res)
	local photos = resolvePhotos(cmd)
	res:put('count', 'i', #photos)
	for i, p in ipairs(photos) do describePhoto(p, i, res) end
end

function OPS.develop_get(cmd, res)
	local photos = resolvePhotos(cmd)
	res:put('count', 'i', #photos)
	for i, p in ipairs(photos) do
		local okd, ds = LrTasks.pcall(function() return p:getDevelopSettings() end)
		ds = okd and ds or {}
		local keys = {}
		for k in pairs(ds) do keys[#keys + 1] = k end
		table.sort(keys)
		local prefix = 'p' .. i .. '.'
		res:put(prefix .. 'path', 's', photoField(p, function(x) return x:getRawMetadata('path') end, ''))
		for _, k in ipairs(keys) do
			local v = ds[k]
			local t = type(v)
			if t == 'number' then res:put(prefix .. k, 'f', v)
			elseif t == 'boolean' then res:put(prefix .. k, 'b', v)
			elseif t == 'string' then res:put(prefix .. k, 's', v)
			elseif t == 'table' and #v > 0 then res:put(prefix .. k, 'a', v) end
		end
	end
end

function OPS.develop_set(cmd, res)
	local photos, catalog = resolvePhotos(cmd)
	if #photos == 0 then error('没有目标照片（请先选中，或传 path.N）') end

	local settings, n = {}, 0
	for _, k in ipairs(cmd.order) do
		local sub = string.match(k, '^set%.(.+)$')
		if sub then
			settings[sub] = cmd.fields[k]
			n = n + 1
		end
	end
	if n == 0 then error('没有任何 set.* 参数') end

	catalog:withWriteAccessDo('AI 桥接：修改照片参数', function()
		for _, p in ipairs(photos) do
			p:applyDevelopSettings(settings)
		end
	end, { timeout = 60 })

	res:put('count', 'i', #photos)
	res:put('applied', 'i', n)
end

function OPS.meta_set(cmd, res)
	local photos, catalog = resolvePhotos(cmd)
	local rating = tonumber(cmd:get('rating', -1))
	local label = cmd:get('label', nil)
	catalog:withWriteAccessDo('AI 桥接：写入元数据', function()
		for _, p in ipairs(photos) do
			if rating and rating >= 0 then p:setRawMetadata('rating', math.floor(rating)) end
			if label then p:setRawMetadata('colorNameForLabel', label) end
		end
	end, { timeout = 60 })
	res:put('count', 'i', #photos)
end

function OPS.select(cmd, res)
	local photos, catalog = resolvePhotos(cmd)
	if #photos == 0 then error('没有匹配的照片') end
	catalog:setSelectedPhotos(photos[1], photos)
	res:put('count', 'i', #photos)
end

function OPS.reveal(cmd, res)
	local mod = cmd:get('module', 'develop')
	import('LrApplicationView').switchToModule(mod)
	res:put('module', 's', mod)
end

-- LrFileUtils.directoryEntries 返回的是迭代器，不是表
local function listDir(dir)
	local out = {}
	local ok = LrTasks.pcall(function()
		for path in LrFileUtils.directoryEntries(dir) do
			out[#out + 1] = path
		end
	end)
	if not ok then return {} end
	return out
end

local function dirFiles(dir)
	local out = {}
	for _, p in ipairs(listDir(dir)) do
		if LrFileUtils.exists(p) == 'file' then out[#out + 1] = p end
	end
	return out
end

function OPS.export(cmd, res)
	local dest = cmd:get('dest', '')
	if dest == '' then error('缺少 dest（导出目录）') end
	local fmt = string.upper(cmd:get('format', 'JPEG'))
	local q = tonumber(cmd:get('quality', 0.9)) or 0.9
	local longEdge = tonumber(cmd:get('longEdge', 0)) or 0

	local photos = resolvePhotos(cmd)
	if #photos == 0 then error('没有可导出的照片') end

	LrTasks.pcall(function() LrFileUtils.createAllDirectories(dest) end)
	local before = {}
	for _, p in ipairs(dirFiles(dest)) do before[string.lower(p)] = true end

	local settings = {
		LR_export_destinationType = 'specificFolder',
		LR_export_destinationPathPrefix = dest,
		LR_export_useSubfolder = false,
		LR_collisionHandling = 'rename',
		LR_format = fmt,
		LR_jpeg_quality = q,
		LR_export_bitDepth = 8,
		LR_export_colorSpace = 'sRGB',
	}
	local reimport = (tonumber(cmd:get('reimport', 0)) or 0) > 0
	if reimport then
		settings.LR_reimportExportedPhoto = true
		settings.LR_reimportExportedPhotoStackWithOriginal = false
	end
	if longEdge > 0 and fmt ~= 'ORIGINAL' then
		settings.LR_size_doConstrain = true
		settings.LR_size_resizeType = 'longEdge'
		settings.LR_size_maxWidth = longEdge
		settings.LR_size_maxHeight = longEdge
	end

	local session = LrExportSession {
		photosToExport = photos,
		exportSettings = settings,
	}
	session:doExportOnCurrentTask()

	local count = 0
	for _, p in ipairs(dirFiles(dest)) do
		if not before[string.lower(p)] then
			count = count + 1
			res:put('file.' .. count, 's', p)
		end
	end
	res:put('count', 'i', count)
end

function OPS.import(cmd, res)
	local paths = cmd:listOf('path')
	if #paths == 0 then error('缺少 path.N') end
	local catalog = catalogOrError()
	local added, failed, errs = {}, {}, {}
	catalog:withWriteAccessDo('AI 桥接：导入文件', function()
		for _, p in ipairs(paths) do
			local ok1, photo = LrTasks.pcall(function() return catalog:addPhoto(p) end)
			if not (ok1 and photo) then
				local ok2, photo2 = LrTasks.pcall(function() return catalog:addPhoto(p, nil, 'above') end)
				if ok2 and photo2 then ok1, photo = true, photo2 end
			end
			if ok1 and photo then
				added[#added + 1] = photo:getRawMetadata('path')
			else
				failed[#failed + 1] = p
				errs[#errs + 1] = string.format('%s -> %s / %s', p,
					tostring(ok1), tostring(photo))
			end
		end
	end, { timeout = 120 })
	res:put('count', 'i', #added)
	for i, p in ipairs(added) do res:put('path.' .. i, 's', p) end
	res:put('failed', 'i', #failed)
	for i, e in ipairs(errs) do res:put('err.' .. i, 's', e) end
end

function OPS.develop_dump(cmd, res)
	local photos = resolvePhotos(cmd)
	if #photos == 0 then error('没有目标照片') end
	local filter = cmd:get('filter', '')
	local p = photos[1]
	local okd, ds = LrTasks.pcall(function() return p:getDevelopSettings() end)
	if not okd then error('读取参数失败: ' .. tostring(ds)) end
	local flat = {}
	flatten(ds or {}, 'p1', flat, 0)
	local n = 0
	for _, item in ipairs(flat) do
		if filter == '' or string.find(item[1], filter, 1, true) then
			n = n + 1
			res:put(item[1], item[2], item[3])
		end
	end
	res:put('fields', 'i', n)
	res:put('totalFields', 'i', #flat)
end

function OPS.develop_set_tree(cmd, res)
	local photos, catalog = resolvePhotos(cmd)
	if #photos == 0 then error('没有目标照片') end

	local function splitPath(key)
		local parts = {}
		for seg in string.gmatch(key, '[^.]+') do
			if string.match(seg, '^%d+$') then parts[#parts + 1] = tonumber(seg)
			else parts[#parts + 1] = seg end
		end
		return parts
	end

	local function expandInto(root, keys, value)
		local node = root
		for i = 1, #keys - 1 do
			local seg = keys[i]
			if type(node[seg]) ~= 'table' then node[seg] = {} end
			node = node[seg]
		end
		node[keys[#keys]] = value
	end

	local root, n = {}, 0
	for _, k in ipairs(cmd.order) do
		local sub = string.match(k, '^set%.(.+)$')
		if sub then
			expandInto(root, splitPath(sub), cmd.fields[k])
			n = n + 1
		end
	end
	if n == 0 then error('没有 set.* 参数') end

	local ok, err = LrTasks.pcall(function()
		catalog:withWriteAccessDo('AI 桥接：写入蒙版与参数', function()
			for _, p in ipairs(photos) do
				p:applyDevelopSettings(root)
			end
		end, { timeout = 120 })
	end)
	if not ok then error(tostring(err)) end

	res:put('count', 'i', #photos)
	res:put('applied', 'i', n)
end

function OPS.probe_api(cmd, res)
	local catalog = LrApplication.activeCatalog()
	local names = { 'pasteSettings', 'applyDevelopPreset', 'getPhotosAvailableForEditing',
		'getDevelopPresets', 'getDevelopPresetFolders', 'removePhoto', 'createVirtualCopies',
		'setSelectedPhotos', 'addPhoto', 'addPhotos', 'getAllPhotos' }
	for _, n in ipairs(names) do
		local ok, fn = LrTasks.pcall(function() return catalog[n] end)
		res:put('has.' .. n, 's', (ok and fn ~= nil) and type(fn) or 'nil')
	end
	local photo = (catalog:getTargetPhotos() or {})[1]
	if photo then
		local names2 = { 'applyDevelopPreset', 'applyDevelopSettings', 'getDevelopSettings',
			'createVirtualCopy', 'isAvailableForEditing', 'needsUpdateAISettings' }
		for _, n in ipairs(names2) do
			local ok, fn = LrTasks.pcall(function() return photo[n] end)
			res:put('photo.' .. n, 's', (ok and fn ~= nil) and type(fn) or 'nil')
		end
	end
end

function OPS.paste_test(cmd, res)
	local photos, catalog = resolvePhotos(cmd)
	if #photos == 0 then error('没有目标照片') end
	local tbl = {}
	for _, k in ipairs(cmd.order) do
		local sub = string.match(k, '^set%.(.+)$')
		if sub then tbl[sub] = cmd.fields[k] end
	end
	local i = 0
	local function try(label, fn)
		i = i + 1
		local ok, err = LrTasks.pcall(fn)
		res:put('r' .. i, 's', label .. ' => ' .. tostring(ok) ..
			(ok and '' or (' / ' .. tostring(err))))
	end
	try('pasteSettings(photos, tbl)', function() catalog:pasteSettings(photos, tbl) end)
	try('pasteSettings(tbl, photos)', function() catalog:pasteSettings(tbl, photos) end)
	try('pasteSettings(photos)', function() catalog:pasteSettings(photos) end)
end

function OPS.diag(cmd, res)	local catalog = LrApplication.activeCatalog()
	res:put('catalogStr', 's', tostring(catalog))
	local ok, photos = LrTasks.pcall(function() return catalog:getTargetPhotos() end)
	res:put('targetOk', 'b', ok)
	res:put('photosStr', 's', tostring(photos))
	if ok and photos and #photos > 0 then
		local p = photos[1]
		res:put('photoType', 's', type(p))
		res:put('photoStr', 's', tostring(p))
		local okp, v = LrTasks.pcall(function() return p:getRawMetadata('path') end)
		res:put('pathOk', 'b', okp)
		res:put('pathVal', 's', tostring(v))
		local okd, d = LrTasks.pcall(function() return p:getDevelopSettings() end)
		res:put('devOk', 'b', okd)
		res:put('devVal', 's', tostring(d))
		local oki, id = LrTasks.pcall(function() return p.localIdentifier end)
		res:put('idOk', 'b', oki)
		res:put('idVal', 's', tostring(id))
	end
end

function OPS.log(cmd, res)
	M.log('[client] ' .. tostring(cmd:get('msg', '')))
end

-- ---------------------------------------------------------------- 调度

function M.handle(cmdPath)
	local name = string.match(cmdPath, '([^/\\]+)$') or cmdPath
	local id = string.gsub(name, '%.cmd$', '')
	local t0 = os.clock()
	local res = Res.new()
	res:put('id', 's', id)

	local ok, err = LrTasks.pcall(function()
		local text = readFile(cmdPath)
		if not text then error('读不到命令文件') end
		local cmd = parseCmd(text)
		local op = cmd:get('op', '')
		res:put('op', 's', op)
		local fn = OPS[op]
		if not fn then error('未知操作：' .. tostring(op)) end
		fn(cmd, res)
	end)

	if ok then
		res:put('ok', 'b', true)
	else
		res:put('ok', 'b', false)
		res:put('err', 's', tostring(err))
		M.log('命令失败 ' .. id .. '：' .. tostring(err))
	end
	res:put('elapsed', 'f', os.clock() - t0)

	writeFile(OUTBOX .. '\\' .. id .. '.res', res:text())

	-- 沙箱里 os.remove 不可用，必须走 LrFileUtils
	LrTasks.pcall(function() LrFileUtils.delete(cmdPath) end)
end

local lastBeat = 0
local function heartbeat()
	local now = os.time()
	if now - lastBeat < 3 then return end
	lastBeat = now
	writeFile(HEART, string.format('%d|%s|%s', now, VERSION, tostring(M.running)))
end

function M.pollOnce()
	local cmds = {}
	for _, p in ipairs(listDir(INBOX)) do
		if string.sub(p, -4) == '.cmd' then cmds[#cmds + 1] = p end
	end
	table.sort(cmds)
	local n = 0
	for _, p in ipairs(cmds) do
		if n >= 6 then break end
		n = n + 1
		M.handle(p)
	end
end

function M.start()
	M.gen = (M.gen or 0) + 1
	local myGen = M.gen
	M.running = true

	LrTasks.pcall(function()
		LrFileUtils.createAllDirectories(ROOT)
		LrFileUtils.createAllDirectories(INBOX)
		LrFileUtils.createAllDirectories(OUTBOX)
	end)
	M.log(string.format('桥接启动 v%s，root=%s', VERSION, ROOT))

	LrTasks.startAsyncTask(function()
		while M.running and M.gen == myGen do
			local ok, err = LrTasks.pcall(M.pollOnce)
			if not ok then M.log('轮询异常：' .. tostring(err)) end
			LrTasks.pcall(heartbeat)
			LrTasks.sleep(0.4)
		end
		if M.gen == myGen then M.log('桥接停止') end
	end)
end

function M.stop()
	M.running = false
end

function M.restart()
	M.running = false
	LrTasks.startAsyncTask(function()
		LrTasks.sleep(0.5)
		M.start()
	end)
end

-- ---------------------------------------------------------------- 蒙版扩展
-- applyDevelopSettings 无法新增蒙版，AI 选区只能走 LrDevelopController 的
-- UI 函数路径。扩展放独立文件，加载失败不影响主桥接。
pcall(function()
	local path = _PLUGIN and _PLUGIN.path
	if not path then return end
	local chunk = loadfile(path .. '/MaskOps.lua')
	if not chunk then return end
	local mod = chunk()
	if type(mod) == 'table' and type(mod.ops) == 'function' then
		local extra = mod.ops()
		if type(extra) == 'table' then
			for k, v in pairs(extra) do OPS[k] = v end
			M.MASK_OPS = true
			M.log('蒙版扩展已加载')
		end
	end
end)

_G.__AIBRIDGE = M

return M
