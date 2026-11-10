-- 插件卸载 / 禁用时执行

local core = _G.__AIBRIDGE
if core then
	pcall(function() core.stop() end)
end
