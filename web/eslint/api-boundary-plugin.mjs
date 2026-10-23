/** Local ESLint plugin: keeps every call to the Python API inside `lib/api/`.
 * A plugin (not `no-restricted-syntax`) because flat config replaces, never merges, rule options. */

const CLIENT_IMPORT = /(^|\/)lib\/api\/(client|actions)(\.ts)?$/;
const SIBLING_IMPORT = /^\.\/(client|actions)(\.ts)?$/;

function isApiBaseUrlLiteral(node) {
  return node.type === "Literal" && node.value === "API_BASE_URL";
}

function containsApiBaseUrl(node, seen = new Set()) {
  if (!node || typeof node.type !== "string" || seen.has(node)) return false;
  seen.add(node);
  if (node.type === "Identifier" && node.name === "API_BASE_URL") return true;
  if (isApiBaseUrlLiteral(node)) return true;
  for (const [key, value] of Object.entries(node)) {
    if (key === "parent") continue;
    if (Array.isArray(value)) {
      if (value.some((child) => containsApiBaseUrl(child, seen))) return true;
    } else if (value && typeof value === "object" && containsApiBaseUrl(value, seen)) {
      return true;
    }
  }
  return false;
}

const noDirectApiBaseUrl = {
  meta: {
    type: "problem",
    schema: [],
    messages: {
      direct:
        "Do not read API_BASE_URL outside lib/api/. Call the API through api() or apiAction() from @/lib/api.",
    },
  },
  create(context) {
    return {
      MemberExpression(node) {
        const { property, computed } = node;
        const named = !computed && property.type === "Identifier" && property.name === "API_BASE_URL";
        if (named || (computed && isApiBaseUrlLiteral(property))) {
          context.report({ node, messageId: "direct" });
        }
      },
      Property(node) {
        if (node.parent?.type !== "ObjectPattern") return;
        const { key, computed } = node;
        const named = !computed && key.type === "Identifier" && key.name === "API_BASE_URL";
        if (named || isApiBaseUrlLiteral(key)) context.report({ node, messageId: "direct" });
      },
      CallExpression(node) {
        if (node.callee.type !== "Identifier" || node.callee.name !== "fetch") return;
        if (node.arguments.some((arg) => containsApiBaseUrl(arg))) {
          context.report({ node, messageId: "direct" });
        }
      },
    };
  },
};

function hasUseClientDirective(program) {
  for (const statement of program.body) {
    if (statement.type !== "ExpressionStatement" || statement.directive === undefined) return false;
    if (statement.directive === "use client") return true;
  }
  return false;
}

const noClientServerApiImport = {
  meta: {
    type: "problem",
    schema: [],
    messages: {
      serverOnly:
        'Client modules cannot import "{{source}}" (server-only). Use @/lib/api/types and @/lib/api/errors.',
    },
  },
  create(context) {
    let isClient = false;
    const check = (node) => {
      const source = node.source?.value;
      if (!isClient || typeof source !== "string") return;
      if (CLIENT_IMPORT.test(source) || SIBLING_IMPORT.test(source)) {
        context.report({ node, messageId: "serverOnly", data: { source } });
      }
    };
    return {
      Program(node) {
        isClient = hasUseClientDirective(node);
      },
      ImportDeclaration: check,
      ExportNamedDeclaration: check,
      ExportAllDeclaration: check,
    };
  },
};

const plugin = {
  meta: { name: "api-boundary" },
  rules: {
    "no-direct-api-base-url": noDirectApiBaseUrl,
    "no-client-server-api-import": noClientServerApiImport,
  },
};

export default plugin;
