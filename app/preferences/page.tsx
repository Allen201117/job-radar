import Navbar from "@/components/Navbar";
import PreferenceForm from "@/components/PreferenceForm";
import ResumeProfilePanel from "@/components/ResumeProfilePanel";

export default function PreferencesPage() {
  return (
    <div>
      <Navbar />
      <main className="mx-auto max-w-5xl px-4 py-8">
        <h1 className="text-2xl font-semibold tracking-tight">求职偏好</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          设置你的目标城市、岗位方向、关键词。系统会根据这些偏好给岗位打分并排序。
        </p>
        <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(360px,420px)]">
          <PreferenceForm />
          <ResumeProfilePanel />
        </div>
      </main>
    </div>
  );
}
