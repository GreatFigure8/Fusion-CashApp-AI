"use server";

import { refresh } from "next/cache";

import { apiAction } from "@/lib/api/actions";
import { api } from "@/lib/api/client";
import { emailInput, generateInput } from "@/lib/reports/schemas";

const generate = apiAction(generateInput, async ({ date }) => {
  const result = await api("post", "/reports/daily-summary/generate", { body: { date } });
  if (result.ok) refresh();
  return result;
});

const email = apiAction(emailInput, async ({ date, recipients }) => {
  const result = await api("post", "/reports/daily-summary/email", {
    body: recipients ? { date, recipients } : { date },
  });
  if (result.ok) refresh();
  return result;
});

export async function generateDailySummary(input: unknown) {
  return generate(input);
}

export async function emailDailySummary(input: unknown) {
  return email(input);
}
