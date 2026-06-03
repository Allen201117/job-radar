"use client";

import { useState } from "react";
import AddSourceForm from "@/components/AddSourceForm";
import SourceTable from "@/components/SourceTable";

// 把「添加源」表单与源列表组合在一起：表单添加成功后 bump reloadSignal，让表格从库里重拉最新数据。
export default function SourceManager() {
  const [reloadSignal, setReloadSignal] = useState(0);

  return (
    <div className="space-y-5">
      <AddSourceForm onAdded={() => setReloadSignal((n) => n + 1)} />
      <SourceTable reloadSignal={reloadSignal} />
    </div>
  );
}
