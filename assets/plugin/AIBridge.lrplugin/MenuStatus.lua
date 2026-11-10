-- 菜单：查看桥接状态（文件 > 增效工具额外功能 > 桥接 · 查看状态）

local LrDialogs = import 'LrDialogs'
local LrApplication = import 'LrApplication'
local LrFileUtils = import 'LrFileUtils'

local core = _G.__AIBRIDGE

local lines = {}
lines[#lines + 1] = '运行中：' .. (core and tostring(core.running) or '未初始化')
lines[#lines + 1] = '根目录：' .. (core and tostring(core.ROOT) or 'O:\\lr_bridge')

local okc, c = pcall(LrApplication.activeCatalog)
if okc and c then
	lines[#lines + 1] = '目录库：' .. tostring(c:getPath())
	local photos = c:getTargetPhotos() or {}
	lines[#lines + 1] = '当前选中：' .. #photos .. ' 张'
else
	lines[#lines + 1] = '目录库：未打开'
end

local hb = (core and core.ROOT or 'O:\\lr_bridge') .. '\\heartbeat.txt'
if LrFileUtils.exists(hb) == 'file' then
	local f = io.open(hb, 'rb')
	if f then
		lines[#lines + 1] = '心跳：' .. (f:read('*a') or '')
		f:close()
	end
else
	lines[#lines + 1] = '心跳：无（插件未运行）'
end

LrDialogs.message('AI 桥接状态', table.concat(lines, '\n'), 'info')
