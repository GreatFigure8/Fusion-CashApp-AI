import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function SignedOutPage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-4 p-6 text-center">
      <h1 className="text-xl font-semibold tracking-tight">You&apos;ve been signed out.</h1>
      <Button render={<Link href="/auth/sign-in" prefetch={false} />}>Sign in again</Button>
    </main>
  );
}
