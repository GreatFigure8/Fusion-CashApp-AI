import type { Route } from "next";
import { redirect } from "next/navigation";

export default function Home(): never {
  redirect("/dashboard" as Route);
}
