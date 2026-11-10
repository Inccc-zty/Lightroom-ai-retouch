--[[
  AI 桥接插件 —— 声明文件

  关键点（SDK 文档）：
    LrInitPlugin      = '脚本名'   —— 插件加载时运行的脚本
    LrForceInitPlugin = true       —— 强制每次 Lightroom 启动都运行该脚本
  没有 LrForceInitPlugin，LrInitPlugin 只在插件被「首次启用」时跑一次，
  这就是最初桥接迟迟不启动的原因。
]]

return {

	LrSdkVersion = 10.0,
	LrSdkMinimumVersion = 6.0,

	LrToolkitIdentifier = 'com.workbuddy.aiBridge',
	LrPluginName = 'AI 桥接（WorkBuddy）',

	LrInitPlugin = 'PluginInit.lua',
	LrForceInitPlugin = true,
	LrShutdownPlugin = 'PluginShutdown.lua',

	LrExportMenuItems = {
		{
			title = '桥接 · 查看状态',
			file = 'MenuStatus.lua',
		},
		{
			title = '桥接 · 启动 / 重启',
			file = 'MenuStart.lua',
		},
	},

	VERSION = { major = 1, minor = 0, revision = 0 },
}
