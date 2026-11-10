--[[
  MaskOps.lua —— Lightroom 原生蒙版操作扩展

  为什么单独一个文件：
    BridgeCore 的 applyDevelopSettings 无法「新增」蒙版。LR 只在
    getDevelopSettings 已经返回过的键上接受写入，没有蒙版的照片
    永远不会通过这条路长出蒙版（实测写入被静默丢弃）。

    要新增蒙版必须走 LrDevelopController 的 UI 函数路径：
      createNewMask("aiSelection", "sky")
    AI 选区的位图由 Lightroom 自己算好写进 .lrcat-data（RocksDB blob），
    通过 MaskDigest 引用。SDK 无法伪造 digest，所以只能让 LR 自己算。

  本文件由 BridgeCore 在 OPS 表定义之后用 pcall 加载，
  加载失败或运行出错都不影响原有桥接功能。
]]

local LrTasks = import 'LrTasks'
local LrApplication = import 'LrApplication'
local LrApplicationView = import 'LrApplicationView'

local okDC, DC = pcall(import, 'LrDevelopController')

local M = {}

-- ---------------------------------------------------------------- 工具

local function needDC()
	if not okDC or type(DC) ~= 'table' then
		error('LrDevelopController 不可用：' .. tostring(DC))
	end
	return DC
end

local function takePhoto(cmd)
	local catalog = LrApplication.activeCatalog()
	local paths = cmd:listOf('path')
	if #paths == 0 then
		local tp = catalog:getTargetPhotos() or {}
		if #tp == 0 then error('没有选中的照片') end
		return tp[1], catalog
	end
	local ph = catalog:findPhotoByPath(paths[1])
	if not ph then error('找不到照片：' .. paths[1]) end
	return ph, catalog
end

-- 收集 local.Xxx=值 形式的局部调整参数
local function collectLocal(cmd)
	local vals, names = {}, {}
	for _, k in ipairs(cmd.order) do
		local n = string.match(k, '^local%.(.+)$')
		if n then
			vals[n] = cmd.fields[k]
			names[#names + 1] = n
		end
	end
	return vals, names
end

-- 进入 develop 模块 + 激活蒙版工具，并把目标照片设为当前选中
local function focus(photo, catalog)
	local dc = needDC()
	LrTasks.pcall(function() LrApplicationView.switchToModule('develop') end)
	LrTasks.pcall(function()
		catalog:withWriteAccessDo('AI 桥接：定位照片', function()
			catalog:setSelectedPhotos(photo, { photo })
		end, { timeout = 60 })
	end)
	LrTasks.pcall(function() dc.selectTool('masking') end)
	LrTasks.sleep(0.3)
	return dc
end

local function applyLocal(dc, vals, names, res)
	local n = 0
	for _, name in ipairs(names) do
		local v = vals[name]
		if type(v) == 'number' then
			local ok, err = LrTasks.pcall(function()
				dc.setValue('local_' .. name, v)
			end)
			res:put('set.' .. name, 's', ok and 'ok' or ('ERR ' .. tostring(err)))
			n = n + 1
		else
			res:put('set.' .. name, 's', 'skip(非数值)')
		end
	end
	return n
end

-- ---------------------------------------------------------------- 操作

local OPS = {}

-- 创建 AI 选区蒙版并赋局部参数
--   maskSubtype: sky / subject / background / objects / people
--   local.Exposure=0.5  local.Highlights=-40 ...
function OPS.mask_ai(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	local subtype = cmd:get('maskSubtype', 'sky')
	local settle = tonumber(cmd:get('settle', 2.5)) or 2.5

	dc = focus(photo, catalog)

	local before = 0
	LrTasks.pcall(function()
		local ms = dc.getAllMasks()
		if type(ms) == 'table' then before = #ms end
	end)

	local ok, maskId = LrTasks.pcall(function()
		return dc.createNewMask('aiSelection', subtype)
	end)
	if not ok then error('createNewMask 失败：' .. tostring(maskId)) end

	-- AI 位图是异步算的，等它落地再改参数，否则参数会落在空蒙版上
	LrTasks.sleep(settle)

	local id = maskId
	if id == nil then
		LrTasks.pcall(function()
			local ms = dc.getAllMasks()
			if type(ms) == 'table' and #ms > before then id = ms[#ms] end
		end)
	end
	res:put('maskId', 's', tostring(id))
	res:put('maskSubtype', 's', subtype)

	if id then
		LrTasks.pcall(function() dc.selectMask(id) end)
		LrTasks.sleep(0.15)
	end

	local vals, names = collectLocal(cmd)
	res:put('applied', 'i', applyLocal(dc, vals, names, res))
end

-- 在当前蒙版上做布尔运算
--   op: add / intersect / subtract / invert
function OPS.mask_boolean(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)

	local op = cmd:get('op', 'intersect')
	local mtype = cmd:get('maskType', 'rangeMask')
	local msub = cmd:get('maskSubtype', nil)
	local maskId = cmd:get('maskId', nil)

	local ok, err
	if op == 'invert' then
		ok, err = LrTasks.pcall(function()
			dc.invertMask(maskId or dc.getSelectedMask())
		end)
	else
		local fn = ({ add = 'addToCurrentMask', intersect = 'intersectWithCurrentMask',
			subtract = 'subtractFromCurrentMask' })[op]
		if not fn then error('未知布尔运算：' .. tostring(op)) end
		ok, err = LrTasks.pcall(function()
			if msub and msub ~= '' then return dc[fn](mtype, msub) end
			return dc[fn](mtype)
		end)
	end
	if not ok then error(tostring(err)) end
	LrTasks.sleep(1.2)
	res:put('op', 's', op)
end

-- 给指定蒙版设局部参数（先选中再写）
function OPS.mask_set(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)
	local maskId = cmd:get('maskId', nil)
	if maskId and maskId ~= '' then
		LrTasks.pcall(function() dc.selectMask(maskId) end)
		LrTasks.sleep(0.15)
	end
	local vals, names = collectLocal(cmd)
	res:put('applied', 'i', applyLocal(dc, vals, names, res))
end

function OPS.mask_list(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)
	local ms = dc.getAllMasks()
	local n = 0
	if type(ms) == 'table' then
		for k, v in pairs(ms) do
			n = n + 1
			local id = v
			if type(v) == 'table' then
				id = v.maskId or v.id or v[1] or tostring(v)
			end
			res:put('mask.' .. n, 's', tostring(k) .. '=' .. tostring(id))
		end
	end
	res:put('count', 'i', n)
end

function OPS.mask_select(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)
	local maskId = cmd:get('maskId', nil)
	if not maskId or maskId == '' then error('缺少 maskId') end
	local ok, err = LrTasks.pcall(function() dc.selectMask(maskId) end)
	if not ok then error(tostring(err)) end
	res:put('maskId', 's', tostring(maskId))
end

function OPS.mask_delete(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)
	local maskId = cmd:get('maskId', nil)
	local ok, err = LrTasks.pcall(function()
		if maskId and maskId ~= '' then dc.deleteMask(maskId) else dc.deleteMask() end
	end)
	if not ok then error(tostring(err)) end
	LrTasks.sleep(0.3)
	res:put('deleted', 's', tostring(maskId))
end

function OPS.mask_reset(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	dc = focus(photo, catalog)
	LrTasks.pcall(function() dc.resetMasking() end)
	res:put('reset', 'b', true)
end

function OPS.mask_geo(cmd, res)
	local dc = needDC()
	local photo, catalog = takePhoto(cmd)
	local kind = cmd:get('kind', 'radialGradient')
	dc = focus(photo, catalog)
	local ok, maskId = LrTasks.pcall(function()
		return dc.createNewMask(kind)
	end)
	if not ok then error('createNewMask 失败：' .. tostring(maskId)) end
	LrTasks.sleep(0.8)
	res:put('maskId', 's', tostring(maskId))
	if maskId then
		LrTasks.pcall(function() dc.selectMask(maskId) end)
		LrTasks.sleep(0.15)
	end
	local vals, names = collectLocal(cmd)
	res:put('applied', 'i', applyLocal(dc, vals, names, res))
end

-- 探针：这个 LR 版本到底有没有这些蒙版 API
function OPS.mask_probe(cmd, res)
	res:put('dc.available', 'b', okDC and type(DC) == 'table')
	res:put('dc.import', 's', tostring(DC))
	if not (okDC and type(DC) == 'table') then return end
	local names = { 'createNewMask', 'getAllMasks', 'getSelectedMask', 'selectMask',
		'deleteMask', 'invertMask', 'selectTool', 'goToMasking', 'toggleOverlay',
		'resetMasking', 'addToCurrentMask', 'intersectWithCurrentMask',
		'subtractFromCurrentMask', 'setValue', 'getValue', 'selectMaskTool',
		'deleteMaskTool', 'getSelectedMaskTool', 'stepBackward', 'stepForward' }
	for _, n in ipairs(names) do
		local ok, fn = LrTasks.pcall(function() return DC[n] end)
		res:put('has.' .. n, 's', (ok and fn ~= nil) and type(fn) or 'nil')
	end
end

M.ops = function() return OPS end
return M
