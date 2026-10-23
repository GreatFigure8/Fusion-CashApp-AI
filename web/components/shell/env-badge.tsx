import { Pill } from "@/components/common/pill";
import type { Me } from "@/lib/permissions";

/** DEV, TEST, PROD or LOCAL from the API's environment; warn tone for every environment. */
export function EnvPill({ env }: { env: Me["env"] }) {
  return (
    <Pill tone="warn" mono title={`Environment: ${env}`}>
      <span data-env={env}>{env.toUpperCase()}</span>
    </Pill>
  );
}
