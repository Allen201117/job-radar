const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");
const Module = require("node:module");

const ROOT = path.join(__dirname, "..");

function loadTsModule(relativePath) {
  const sourcePath = path.join(ROOT, relativePath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: sourcePath,
  }).outputText;
  const scopedRequire = Module.createRequire(sourcePath);
  const mod = { exports: {} };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports,
    scopedRequire,
    mod,
    sourcePath,
    path.dirname(sourcePath),
  );
  return mod.exports;
}

function jsonResponse(body, init = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status || 200,
    headers: { "content-type": "application/json", ...(init.headers || {}) },
  });
}

function loadRoute(relativePath, mocks = {}) {
  const sourcePath = path.join(ROOT, relativePath);
  const source = fs.readFileSync(sourcePath, "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      esModuleInterop: true,
    },
    fileName: sourcePath,
  }).outputText;

  const scopedRequire = Module.createRequire(sourcePath);
  const routeMocks = {
    "next/server": {
      NextRequest: class NextRequest {},
      NextResponse: { json: jsonResponse },
    },
    ...mocks,
  };
  const localRequire = (request) => {
    if (Object.prototype.hasOwnProperty.call(routeMocks, request)) {
      return routeMocks[request];
    }
    if (request.startsWith("@/")) {
      return scopedRequire(path.join(ROOT, request.slice(2)));
    }
    return scopedRequire(request);
  };

  const mod = { exports: {} };
  new Function("exports", "require", "module", "__filename", "__dirname", compiled)(
    mod.exports,
    localRequire,
    mod,
    sourcePath,
    path.dirname(sourcePath),
  );
  return mod.exports;
}

function resolvedQuery(result = { data: [], error: null }) {
  const filters = [];
  const query = {
    filters,
    select() {
      return this;
    },
    insert() {
      return this;
    },
    update() {
      return this;
    },
    delete() {
      return this;
    },
    upsert() {
      return this;
    },
    eq(column, value) {
      filters.push([column, value]);
      return this;
    },
    in() {
      return this;
    },
    is() {
      return this;
    },
    neq() {
      return this;
    },
    gte() {
      return this;
    },
    lt() {
      return this;
    },
    order() {
      return this;
    },
    limit() {
      return this;
    },
    range() {
      return this;
    },
    single: async () => result,
    maybeSingle: async () => result,
    then(resolve, reject) {
      return Promise.resolve(result).then(resolve, reject);
    },
  };
  return query;
}

module.exports = {
  jsonResponse,
  loadRoute,
  loadTsModule,
  resolvedQuery,
};
