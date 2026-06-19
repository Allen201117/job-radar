import { createServerSupabase } from "@/lib/auth";
import LandingClient from "./landing-client";

export const dynamic = "force-dynamic";

export default async function LandingPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  return <LandingClient loggedIn={!!user} />;
}
