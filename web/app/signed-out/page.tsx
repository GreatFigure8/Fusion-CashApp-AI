import Link from "next/link";

import { actionButtonVariants } from "@/components/common/action-button";
import { GlassPanel } from "@/components/common/glass-panel";
import { MonoLabel } from "@/components/common/mono-label";

export default function SignedOutPage() {
  return (
    <main className="bg-blueprint grid flex-1 place-items-center p-6">
      <GlassPanel as="div" className="flex w-full max-w-md flex-col items-center gap-4 p-8 text-center">
        <MonoLabel>Signed out</MonoLabel>
        <h1 className="text-xl font-semibold tracking-tight">You&apos;ve been signed out.</h1>
        <Link
          href="/auth/sign-in"
          prefetch={false}
          className={actionButtonVariants({ variant: "default", glow: true })}
        >
          Sign in again
        </Link>
      </GlassPanel>
    </main>
  );
}
