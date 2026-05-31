import Navbar from "@/components/Navbar";
import SourceTable from "@/components/SourceTable";
import { isAdmin } from "@/lib/auth";
import { redirect } from "next/navigation";

export const dynamic = "force-dynamic";

export default async function SourcesPage() {
  if (!(await isAdmin())) {
    redirect("/");
  }

  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">数据源管理</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          企业招聘源的状态与抓取日志。
        </p>
        <div className="mt-6">
          <SourceTable />
        </div>
      </main>
    </div>
  );
}
