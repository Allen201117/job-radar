"use client";

import { useState } from "react";
import AddSourceForm from "@/components/AddSourceForm";
import SourceTable from "@/components/SourceTable";
import CompanyWatchQueue from "@/components/CompanyWatchQueue";

// 把「添加源」表单、用户关注队列与源列表组合在一起：表单添加成功后 bump reloadSignal，让表格重拉最新数据。
export default function SourceManager() {
  const [reloadSignal, setReloadSignal] = useState(0);

  return (
    <div className="space-y-5">
      <AddSourceForm onAdded={() => setReloadSignal((n) => n + 1)} />
      <CompanyWatchQueue />
      <SourceTable reloadSignal={reloadSignal} />
    </div>
  );
}
