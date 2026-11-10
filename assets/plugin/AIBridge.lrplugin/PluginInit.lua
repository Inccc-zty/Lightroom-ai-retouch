-- 插件加载 / Lightroom 启动时执行
-- 由 Info.lua 的 LrInitPlugin + LrForceInitPlugin 触发，负责拉起后台桥接循环。

local mark = { at = os.date('%Y-%m-%d %H:%M:%S') }

local function loadCore()
	local ok, mod = pcall(require, 'BridgeCore')
	if ok and type(mod) == 'table' then return mod, 'require' end

	local path = _PLUGIN and _PLUGIN.path
	if not path then return nil, 'no _PLUGIN.path' end

	local chunk, err = loadfile(path .. '/BridgeCore.lua')
	if not chunk then return nil, 'loadfile: ' .. tostring(err) end

	local ok2, mod2 = pcall(chunk)
	if ok2 and type(mod2) == 'table' then return mod2, 'loadfile' end
	return nil, 'run: ' .. tostring(mod2)
end

local core, how = loadCore()
mark.how = tostring(how)
mark.core = tostring(core ~= nil)

if core then
	_G.__AIBRIDGE = core
	local ok, err = pcall(function() core.start() end)
	mark.start = tostring(ok) .. ' / ' .. tostring(err)
end

pcall(function()
	local p = import('LrPrefs').prefsForPlugin()
	p.bridgeMark = mark
end)
