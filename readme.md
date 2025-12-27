# Project Introduction

## 本项目为OSHS-GUI的简化实现版本

[🔗 点我访问源仓库](https://github.com/Tobi1chi/VtolVR_OSHS-GUI)


### Server的绿皮实现
- 自动切图
- 保存flightlog
- 保存replay并和flight打包成压缩包

### 当前可能会有的问题
- VtolVR在每一局结束之后的AutoSave的Replay并不是立刻生成的（至少我没发现生成的逻辑），所以导致了打包之后不一定压缩包里面就有回放的文件。不过flightlog部分不受影响 (✅已完成)
- 接着上一个问题，AutoSave如果延迟保存的话有可能造成包里面的flightlog和回放文件对不上号（✅已完成）
- 这个版本的延迟都用的阻塞的方式实现，中途没法同时处理其他任务。如果后续想修改可以用threading加上这个repo里面的Timer.py来做计时器 (✅已完成）
- 当前的这个版本适合做没有结束条件的PvP地图（没做任务结束的检测），只能等到时间了才切地图

### 下一步开发
- Replay文件保存方式（现在default AutoSave的方式有点问题，游戏目前不太会再要重新开地图的情况下生成保存的地图文件夹） （✅已完成)
- 启用记分系统 (✅已完成)
  - 找到游戏内的人谁是谁（在线玩家注册，记录当前pilot name, steam id）
-记分系统改进：
  - 定期更新获取某些信息（主动请求），比如flightlog，actor list 
    - 查询是否有新的击杀记录
    - 如果有的话读取击杀记录，判断匹配的玩家（可能需要考虑重复飞行员id的问题，所以要有一个在线玩家注册机制，靠steam id来区分），然后sendlog 发送elo的更新信息
  - 找到一个好的方法来测算cfit击杀记分（撞地死亡，根据距离算击杀得分），同样包括队友状态信息的更新（判断是否为有效击杀，当前的判断方式是跟着flightlog走的）
    - 感觉可以通过list air的方式获取所有飞机信息（定时更新），找到所有be killed记录（自杀），计算当前缓存帧数据里面这个玩家到其他玩家之间的距离
- 与记分系统对应的数据库查询（discord/qq bot之类的）（✅已完成）
- Discord bot优化（增加查询指令，优化查询效果...）
- AI chat优化（让AI可以主动访问数据库并获取相应的信息）
  - 优化当前的prompt
  - 给AI提供一些可以被调用的接口
- PVE 模式：
  - 将现有的PVE_Elo运用起来（才不是要变成bvvd疯狂收割玩家时间）
  - 根据挂载来算经济系统（可选项，low priority）
  - 


# Appendix

## Gameserver Socket命令

    "name": "sethost",
    "help": "Set host parameters: sethost [name|password|uniticon|campaign|mission] <value>"

    "name": "checkhost",
    "help": "Check current host settings"

    "name": "config",
    "help": "Config a multiplayer game"

    "name": "host",
    "help": "Host a multiplayer game"

    "name": "listscene",
    "help": "List available scenes"

    "name": "start",
    "help": "Start the multiplayer game"

    "name": "skip",
    "help": "Skip current missions"

    "name": "quit",
    "help": "Quit the multiplayer game"

    "name": "restart",
    "help": "Restart the multiplayer game"

    "name": "sendlog",
    "help": "Send a log message to the game: sendlog [message]"

    "name": "player",
    "help": "List connected players"

    "name": "help",
    "help": "Show this help message"

    "name": "list",
    "help": "List actors (type: all/enemy/friendly/air/ground)"

    "name": "test",
    "help": "Run a test command"

    "name": "scene",
    "help": "Get current scene name"

    "name": "readyroom",
    "help": "Go to multiplayer ready room"

    "name": "flightlog",
    "help": "Get flight log entries"

    "name": "getstage",
    "help": "Get current mission stage"

    "name": "exitapp",
    "help": "Exit application"

## Example
### 开始游戏（首次开始）

    sethost name SERVERNAME
    sethost password PASSWORD //public server if the PASSWORD is empty
    sethost uniticon false //近距离敌方/友方括号标记
    sethost campaign WSID 
    sethost mission MAP_NAME
    config
    //这里最好delay一分钟
    host
    //等待服务器传回Lobby Created的标识
    start //需要等待host完成

### 切换地图（restart）

    getstage //查看当前任务阶段
    //如果是3-inmission
    skip
    //如果是4a/4b代表任务已经结束，不需要再skip
    
    //重新sethost campaign/sethost mission来切换地图
    //delay一段时间让玩家有机会操作回放/总结聊天
    //这里可以保存flightlog到数据库中
    //另外可以参考Tools/AutoSave_Replay.py里面的内容
    //来将游戏生成的回放文件也一并存起来(文件夹)

    restart
    //等待完成标识LobbyReady
    start //重新开始任务


### 任务完成标识

    //成功config，收到后可以host
    {
    "type": "r",
    "src": "HostConfig",
    "msg": true
    }

    //成功创建房间，收到后可以start
    {
    "type": "s",
    "src": "LobbyReady",
    "msg": ""
    }
