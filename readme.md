**本项目为OSHS-GUI的简化实现版本**

[🔗 点我访问源仓库](https://github.com/Tobi1chi/VtolVR_OSHS-GUI)


**Server的绿皮实现**
- 自动切图
- 保存flightlog
- 保存replay并和flight打包成压缩包

**当前可能会有的问题**
- VtolVR在每一局结束之后的AutoSave的Replay并不是立刻生成的（至少我没发现生成的逻辑），所以导致了打包之后不一定压缩包里面就有回放的文件。不过flightlog部分不受影响
- 接着上一个问题，AutoSave如果延迟保存的话有可能造成包里面的flightlog和回放文件对不上号（岔开了）
- 这个版本的延迟都用的阻塞的方式实现，中途没法同时处理其他任务。如果后续想修改可以用threading加上这个repo里面的Timer.py来做计时器
- 当前的这个版本适合做没有结束条件的PvP地图（没做任务结束的检测），只能等到时间了才切地图