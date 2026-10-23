import type { components, paths } from "./schema";

export type { components, paths };

export type HttpMethod = "get" | "put" | "post" | "delete" | "patch";
export type ApiPath = keyof paths & string;

/** The methods the path declares. */
export type Method<P extends ApiPath> = {
  [M in HttpMethod]: NonNullable<paths[P][M]> extends never ? never : M;
}[HttpMethod];

type Operation<P extends ApiPath, M extends Method<P>> = NonNullable<paths[P][M]>;

type Field<T, K extends string> = T extends { [key in K]?: infer V } ? NonNullable<V> : never;

export type PathParamsOf<P extends ApiPath, M extends Method<P>> = Field<
  Field<Operation<P, M>, "parameters">,
  "path"
>;

export type QueryOf<P extends ApiPath, M extends Method<P>> = Field<
  Field<Operation<P, M>, "parameters">,
  "query"
>;

type JsonOf<T> = T extends { content: { "application/json": infer J } } ? J : never;

export type BodyOf<P extends ApiPath, M extends Method<P>> = JsonOf<
  Field<Operation<P, M>, "requestBody">
>;

type ResponsesOf<P extends ApiPath, M extends Method<P>> = Field<Operation<P, M>, "responses">;

type SuccessJson<R> =
  | (R extends { 200: infer T } ? JsonOf<T> : never)
  | (R extends { 201: infer T } ? JsonOf<T> : never)
  | (R extends { 202: infer T } ? JsonOf<T> : never);

/** The success payload: the JSON of 200, 201 and 202, plus undefined when 204 is declared. */
export type ResponseOf<P extends ApiPath, M extends Method<P>> =
  | SuccessJson<ResponsesOf<P, M>>
  | (ResponsesOf<P, M> extends { 204: unknown } ? undefined : never);

export type Schemas = components["schemas"];

type HasKeys<T> = [T] extends [never] ? false : keyof T extends never ? false : true;

type ParamsOption<P extends ApiPath, M extends Method<P>> =
  HasKeys<PathParamsOf<P, M>> extends true
    ? { params: PathParamsOf<P, M> }
    : { params?: PathParamsOf<P, M> };

type BodyOption<P extends ApiPath, M extends Method<P>> = Operation<P, M> extends {
  requestBody: unknown;
}
  ? { body: BodyOf<P, M> }
  : { body?: BodyOf<P, M> };

/** `params` is required when the operation has path params, `body` when it needs a JSON body. */
export type ApiRequestOptions<P extends ApiPath, M extends Method<P>> = ParamsOption<P, M> &
  BodyOption<P, M> & {
    query?: QueryOf<P, M>;
    signal?: AbortSignal;
    requestId?: string;
  };

/** The trailing argument list of `api()`: the options may be omitted only when none is required. */
export type ApiArgs<P extends ApiPath, M extends Method<P>> = object extends ApiRequestOptions<P, M>
  ? [options?: ApiRequestOptions<P, M>]
  : [options: ApiRequestOptions<P, M>];
