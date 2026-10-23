import { ErrorAlert } from "@/components/common/error-alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ApiError } from "@/lib/api/errors";
import type { Schemas } from "@/lib/api/types";
import type { Result } from "@/lib/result";

import { AliasesTable } from "./aliases-table";

export const ALIAS_PAGE_SIZE = 50;

/** Search form (a plain GET, so no JS needed) over the aliases table. */
export function AliasesPanel({
  result,
  q,
  pageNumber,
  canEdit,
}: {
  result: Result<Schemas["AliasPage"], ApiError>;
  q: string;
  pageNumber: number;
  canEdit: boolean;
}) {
  return (
    <div className="space-y-4">
      <form method="get" role="search" className="flex gap-2">
        <input type="hidden" name="tab" value="aliases" />
        <Input
          name="aq"
          defaultValue={q}
          aria-label="Search aliases"
          placeholder="Search aliases"
          className="max-w-xs"
        />
        <Button type="submit" variant="outline">
          Search
        </Button>
      </form>
      {!result.ok ? (
        <ErrorAlert error={result.error} title="Couldn't load the aliases" />
      ) : (
        <AliasesTable
          items={result.value.items}
          total={result.value.total}
          page={pageNumber}
          pageSize={ALIAS_PAGE_SIZE}
          canEdit={canEdit}
        />
      )}
    </div>
  );
}
