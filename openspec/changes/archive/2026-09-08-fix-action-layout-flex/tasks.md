## 任务

- [x] 1 ActionPage 真实布局改用 flex（抽屉定宽可收、主区 flex:1 minWidth:0）；`npm run build` 通过
- [x] 2 dev-log「迭代 37」+ archive（【测试证据】+【反思】）

【测试证据】npm run build ✅；布局从旧 grid(1.65fr/1fr) 改 flex：抽屉定宽 300/收 60，主区 flex:1+minWidth:0 占满剩余。
【反思】复用遗留 CSS 类名时先确认其含义（.action-layout 是旧双卡 grid），抽屉化必须换语义正确的 flex 容器，而不是堆 inline 在错误 grid 里。
