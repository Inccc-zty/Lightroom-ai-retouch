-- 菜单：启动 / 重启桥接（文件 > 增效工具额外功能 > 桥接 · 启动 / 重启）

local LrTasks = import 'LrTasks'
local LrDialogs = import 'LrDialogs'

local function loadCore()
	local core = _G.__AIBRIDGE
	if core then return core end

	local ok, mod = pcall(require, 'BridgeCore')
	if ok and type(mod) == 'table' then
		_G.__AIBRIDGE = mod
		return mod
	end

	local chunk = loadfile(_PLUGIN.path .. '/BridgeCore.lua')
	if chunk then
		local ok2, mod2 = pcall(chunk)
		if ok2 and type(mod2) == 'table' then
			_G.__AIBRIDGE = mod2
			return mod2
		end
	end
	return nil
end

LrTasks.startAsyncTask(function()
	local core = loadCore()
	if not core then
		LrDialogs.message('AI 桥接', '内核加载失败，请查看 lrc_console.log', 'critical')
		return
	end
	core.restart()
	LrTasks.sleep(1.5)
	LrDialogs.message('AI 桥接', '已启动\n根目录：' .. tostring(core.ROOT), 'info')
end)
