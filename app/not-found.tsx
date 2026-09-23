import Link from "next/link";
import Navbar from "@/components/Navbar";
import { ProductPage } from "@/components/ProductChrome";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-editorial">
      <Navbar />
      <ProductPage maxWidth="max-w-5xl">
        <main className="surface mx-auto mt-10 max-w-xl p-8 text-center sm:p-12">
          <p className="t-label text-tone-amber-fg">页面没有找到</p>
          <h1 className="mt-3 t-h1">这个页面可能已移动或不存在</h1>
          <p className="mt-3 t-body-sm ink-2">你可以回到推荐页继续看适合的岗位，或去职位库重新搜索。</p>
          <div className="mt-7 flex flex-wrap justify-center gap-3">
            <Link href="/today" className="btn-ink">
              回到推荐页
            </Link>
            <Link href="/jobs" className="btn-ghost">
              去职位库
            </Link>
          </div>
        </main>
      </ProductPage>
    </div>
  );
}
