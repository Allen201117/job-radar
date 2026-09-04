# 已废弃的组件

组件不再推荐使用时**搬到这里，不要直接删**。做法学自 GitHub Primer 的 `src/deprecated/`。

## 为什么不直接删

直接删会把「组件库改版」变成「全站必须同一天跟着改完」，这在只有几个人的团队里做不到，
结果就是没人敢改组件库。搬进 deprecated 之后，旧调用方还能跑，新代码走新组件，
迁移可以按自己的节奏来。

## 怎么废弃一个组件

1. 把文件从 `components/ui/` 移到 `components/ui/deprecated/`。
2. 在组件的 JSDoc 上加 `@deprecated`，**必须写清楚用什么替代**：

   ```ts
   /** @deprecated 改用 `<Badge tone="sky">`。这个只支持一种尺寸，且颜色是写死的。 */
   ```

   加了 `@deprecated` 之后，IDE 会自动给所有调用处画删除线，不用挨个通知人。
3. `components/ui/index.ts` 的导出改成从 `./deprecated/<name>` 导出（路径变了，调用方不用改）。
4. 在这里追加一行：什么时候废的、为什么、替代品是什么。

## 什么时候可以真删

`grep -r "<组件名>" app components` 为零之后。删除单独提一个 commit，不要混在别的改动里。

## 记录

（暂无。组件库 2026-09-04 建立。）
