# 代码提交规范
## 工作流
1. 创建 worktree 分支：
   ```bash
   git worktree add ../claude/worktree/分支名 -b 分支名 master
   ```
2. 在 worktree 中修改并提交
3. **不合并**，由用户 Code Review 后手动合入
## 分支命名
```
<type>Task No. subject
```
## Commit 格式
```
<type>(<scope>): <subject>
[body]
[footer]
```
## 技术版本
| 组件 | 版本 |
|------|------|
| Go | 1.26.0 |
| Python（ulysses） | 3.12 |
| SQLite | 3.51.2 |