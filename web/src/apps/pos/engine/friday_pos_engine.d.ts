/* tslint:disable */
/* eslint-disable */

export class PosCart {
    free(): void;
    [Symbol.dispose](): void;
    add_line(description: string, quantity: number, unit_price_cents: bigint, product_id?: string | null, unit_cost_cents?: bigint | null): void;
    /**
     * Finalize the cart into a Sale ready to sync, as a JSON string the
     * JS side hands to `PosOfflineQueue::enqueue_json`. `payments_json`
     * is an optional JSON array of `{method, amount_cents}` for a
     * split-tender sale (e.g. part cash, part card) -- omit it (JS:
     * `undefined`) for the ordinary single-tender case, where `method`
     * alone describes the whole sale same as always.
     */
    checkout_json(currency: string, method: string, now_ms: number, payments_json?: string | null): string;
    clear(): void;
    lines_json(): string;
    constructor(tax_rate_bp: bigint);
    remove_line(index: number): boolean;
    set_line_discount_bp(index: number, discount_bp: bigint): boolean;
    subtotal_cents(): bigint;
    tax_cents(): bigint;
    total_cents(): bigint;
}

export class PosOfflineQueue {
    free(): void;
    [Symbol.dispose](): void;
    enqueue_json(sale_json: string): void;
    len(): number;
    mark_synced(client_sale_id: string): void;
    constructor();
    pending_json(): string;
    static restore_json(json: string): PosOfflineQueue;
    /**
     * Persist the whole queue (e.g. to IndexedDB) between sessions.
     */
    to_json(): string;
}

export type InitInput = RequestInfo | URL | Response | BufferSource | WebAssembly.Module;

export interface InitOutput {
    readonly memory: WebAssembly.Memory;
    readonly __wbg_poscart_free: (a: number, b: number) => void;
    readonly __wbg_posofflinequeue_free: (a: number, b: number) => void;
    readonly poscart_add_line: (a: number, b: number, c: number, d: number, e: bigint, f: number, g: number, h: number, i: bigint) => void;
    readonly poscart_checkout_json: (a: number, b: number, c: number, d: number, e: number, f: number, g: number, h: number) => [number, number, number, number];
    readonly poscart_clear: (a: number) => void;
    readonly poscart_lines_json: (a: number) => [number, number];
    readonly poscart_new: (a: bigint) => number;
    readonly poscart_remove_line: (a: number, b: number) => number;
    readonly poscart_set_line_discount_bp: (a: number, b: number, c: bigint) => number;
    readonly poscart_subtotal_cents: (a: number) => bigint;
    readonly poscart_tax_cents: (a: number) => bigint;
    readonly poscart_total_cents: (a: number) => bigint;
    readonly posofflinequeue_enqueue_json: (a: number, b: number, c: number) => [number, number];
    readonly posofflinequeue_len: (a: number) => number;
    readonly posofflinequeue_mark_synced: (a: number, b: number, c: number) => void;
    readonly posofflinequeue_new: () => number;
    readonly posofflinequeue_pending_json: (a: number) => [number, number];
    readonly posofflinequeue_restore_json: (a: number, b: number) => number;
    readonly posofflinequeue_to_json: (a: number) => [number, number];
    readonly __wbindgen_exn_store: (a: number) => void;
    readonly __externref_table_alloc: () => number;
    readonly __wbindgen_externrefs: WebAssembly.Table;
    readonly __wbindgen_malloc: (a: number, b: number) => number;
    readonly __wbindgen_realloc: (a: number, b: number, c: number, d: number) => number;
    readonly __wbindgen_free: (a: number, b: number, c: number) => void;
    readonly __externref_table_dealloc: (a: number) => void;
    readonly __wbindgen_start: () => void;
}

export type SyncInitInput = BufferSource | WebAssembly.Module;

/**
 * Instantiates the given `module`, which can either be bytes or
 * a precompiled `WebAssembly.Module`.
 *
 * @param {{ module: SyncInitInput }} module - Passing `SyncInitInput` directly is deprecated.
 *
 * @returns {InitOutput}
 */
export function initSync(module: { module: SyncInitInput } | SyncInitInput): InitOutput;

/**
 * If `module_or_path` is {RequestInfo} or {URL}, makes a request and
 * for everything else, calls `WebAssembly.instantiate` directly.
 *
 * @param {{ module_or_path: InitInput | Promise<InitInput> }} module_or_path - Passing `InitInput` directly is deprecated.
 *
 * @returns {Promise<InitOutput>}
 */
export default function __wbg_init (module_or_path?: { module_or_path: InitInput | Promise<InitInput> } | InitInput | Promise<InitInput>): Promise<InitOutput>;
