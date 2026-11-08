/* @ts-self-types="./friday_pos_engine.d.ts" */

export class PosCart {
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        PosCartFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_poscart_free(ptr, 0);
    }
    /**
     * @param {string} description
     * @param {number} quantity
     * @param {bigint} unit_price_cents
     * @param {string | null} [product_id]
     * @param {bigint | null} [unit_cost_cents]
     */
    add_line(description, quantity, unit_price_cents, product_id, unit_cost_cents) {
        const val3 = +quantity;
        const val4 = BigInt.asIntN(64, unit_price_cents);
        const val5 = BigInt.asIntN(64, (isLikeNone(unit_cost_cents) ? BigInt(0) : unit_cost_cents));
        let ptr0, len0, ptr1, len1;
        try {
            ptr0 = passStringToWasm0(description, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            len0 = WASM_VECTOR_LEN;
            ptr1 = isLikeNone(product_id) ? 0 : passStringToWasm0(product_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
            len1 = WASM_VECTOR_LEN;
        } catch (e) {
            if (ptr1) { wasm.__wbindgen_free(ptr1, len1 * 1, 1); }
            if (ptr0) { wasm.__wbindgen_free(ptr0, len0 * 1, 1); }
            throw e;
        }
        wasm.poscart_add_line(this.__wbg_ptr, ptr0, len0, val3, val4, ptr1, len1, !isLikeNone(unit_cost_cents), val5);
    }
    /**
     * Finalize the cart into a Sale ready to sync, as a JSON string the
     * JS side hands to `PosOfflineQueue::enqueue_json`. `payments_json`
     * is an optional JSON array of `{method, amount_cents}` for a
     * split-tender sale (e.g. part cash, part card) -- omit it (JS:
     * `undefined`) for the ordinary single-tender case, where `method`
     * alone describes the whole sale same as always.
     * @param {string} currency
     * @param {string} method
     * @param {number} now_ms
     * @param {string | null} [payments_json]
     * @returns {string}
     */
    checkout_json(currency, method, now_ms, payments_json) {
        let deferred6_0;
        let deferred6_1;
        try {
            const val4 = +now_ms;
            let ptr0, len0, ptr1, len1, ptr2, len2;
            try {
                ptr0 = passStringToWasm0(currency, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
                len0 = WASM_VECTOR_LEN;
                ptr1 = passStringToWasm0(method, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
                len1 = WASM_VECTOR_LEN;
                ptr2 = isLikeNone(payments_json) ? 0 : passStringToWasm0(payments_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
                len2 = WASM_VECTOR_LEN;
            } catch (e) {
                if (ptr2) { wasm.__wbindgen_free(ptr2, len2 * 1, 1); }
                if (ptr1) { wasm.__wbindgen_free(ptr1, len1 * 1, 1); }
                if (ptr0) { wasm.__wbindgen_free(ptr0, len0 * 1, 1); }
                throw e;
            }
            const ret = wasm.poscart_checkout_json(this.__wbg_ptr, ptr0, len0, ptr1, len1, val4, ptr2, len2);
            var ptr5 = ret[0];
            var len5 = ret[1];
            if (ret[3]) {
                ptr5 = 0; len5 = 0;
                throw takeFromExternrefTable0(ret[2]);
            }
            deferred6_0 = ptr5;
            deferred6_1 = len5;
            return getStringFromWasm0(ptr5, len5);
        } finally {
            wasm.__wbindgen_free(deferred6_0, deferred6_1, 1);
        }
    }
    clear() {
        wasm.poscart_clear(this.__wbg_ptr);
    }
    /**
     * @returns {string}
     */
    lines_json() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.poscart_lines_json(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {bigint} tax_rate_bp
     */
    constructor(tax_rate_bp) {
        const ret = wasm.poscart_new(tax_rate_bp);
        this.__wbg_ptr = ret;
        PosCartFinalization.register(this, this.__wbg_ptr, this);
        return this;
    }
    /**
     * @param {number} index
     * @returns {boolean}
     */
    remove_line(index) {
        const ret = wasm.poscart_remove_line(this.__wbg_ptr, index);
        return ret !== 0;
    }
    /**
     * @param {number} index
     * @param {bigint} discount_bp
     * @returns {boolean}
     */
    set_line_discount_bp(index, discount_bp) {
        const ret = wasm.poscart_set_line_discount_bp(this.__wbg_ptr, index, discount_bp);
        return ret !== 0;
    }
    /**
     * @returns {bigint}
     */
    subtotal_cents() {
        const ret = wasm.poscart_subtotal_cents(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {bigint}
     */
    tax_cents() {
        const ret = wasm.poscart_tax_cents(this.__wbg_ptr);
        return ret;
    }
    /**
     * @returns {bigint}
     */
    total_cents() {
        const ret = wasm.poscart_total_cents(this.__wbg_ptr);
        return ret;
    }
}
if (Symbol.dispose) PosCart.prototype[Symbol.dispose] = PosCart.prototype.free;

export class PosOfflineQueue {
    static __wrap(ptr) {
        const obj = Object.create(PosOfflineQueue.prototype);
        obj.__wbg_ptr = ptr;
        PosOfflineQueueFinalization.register(obj, obj.__wbg_ptr, obj);
        return obj;
    }
    __destroy_into_raw() {
        const ptr = this.__wbg_ptr;
        this.__wbg_ptr = 0;
        PosOfflineQueueFinalization.unregister(this);
        return ptr;
    }
    free() {
        const ptr = this.__destroy_into_raw();
        wasm.__wbg_posofflinequeue_free(ptr, 0);
    }
    /**
     * @param {string} sale_json
     */
    enqueue_json(sale_json) {
        const ptr0 = passStringToWasm0(sale_json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.posofflinequeue_enqueue_json(this.__wbg_ptr, ptr0, len0);
        if (ret[1]) {
            throw takeFromExternrefTable0(ret[0]);
        }
    }
    /**
     * @returns {number}
     */
    len() {
        const ret = wasm.posofflinequeue_len(this.__wbg_ptr);
        return ret >>> 0;
    }
    /**
     * @param {string} client_sale_id
     */
    mark_synced(client_sale_id) {
        const ptr0 = passStringToWasm0(client_sale_id, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        wasm.posofflinequeue_mark_synced(this.__wbg_ptr, ptr0, len0);
    }
    constructor() {
        const ret = wasm.posofflinequeue_new();
        this.__wbg_ptr = ret;
        PosOfflineQueueFinalization.register(this, this.__wbg_ptr, this);
        return this;
    }
    /**
     * @returns {string}
     */
    pending_json() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.posofflinequeue_pending_json(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
    /**
     * @param {string} json
     * @returns {PosOfflineQueue}
     */
    static restore_json(json) {
        const ptr0 = passStringToWasm0(json, wasm.__wbindgen_malloc, wasm.__wbindgen_realloc);
        const len0 = WASM_VECTOR_LEN;
        const ret = wasm.posofflinequeue_restore_json(ptr0, len0);
        return PosOfflineQueue.__wrap(ret);
    }
    /**
     * Persist the whole queue (e.g. to IndexedDB) between sessions.
     * @returns {string}
     */
    to_json() {
        let deferred1_0;
        let deferred1_1;
        try {
            const ret = wasm.posofflinequeue_to_json(this.__wbg_ptr);
            deferred1_0 = ret[0];
            deferred1_1 = ret[1];
            return getStringFromWasm0(ret[0], ret[1]);
        } finally {
            wasm.__wbindgen_free(deferred1_0, deferred1_1, 1);
        }
    }
}
if (Symbol.dispose) PosOfflineQueue.prototype[Symbol.dispose] = PosOfflineQueue.prototype.free;
function __wbg_get_imports() {
    const import0 = {
        __proto__: null,
        __wbg_Error_208446807d0d1e30: function(arg0, arg1) {
            const ret = Error(getStringFromWasm0(arg0, arg1));
            return ret;
        },
        __wbg___wbindgen_throw_4c88d8bf264fd984: function(arg0, arg1) {
            throw new Error(getStringFromWasm0(arg0, arg1));
        },
        __wbg_getRandomValues_19b7c67932c07470: function() { return handleError(function (arg0, arg1) {
            globalThis.crypto.getRandomValues(getArrayU8FromWasm0(arg0, arg1));
        }, arguments); },
        __wbindgen_init_externref_table: function() {
            const table = wasm.__wbindgen_externrefs;
            table.set(0, undefined);
            table.set(1024, undefined);
            table.set(1025, null);
            table.set(1026, true);
            table.set(1027, false);
        },
    };
    return {
        __proto__: null,
        "./friday_pos_engine_bg.js": import0,
    };
}

const PosCartFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_poscart_free(ptr, 1));
const PosOfflineQueueFinalization = (typeof FinalizationRegistry === 'undefined')
    ? { register: () => {}, unregister: () => {} }
    : new FinalizationRegistry(ptr => wasm.__wbg_posofflinequeue_free(ptr, 1));

function addToExternrefTable0(obj) {
    const idx = wasm.__externref_table_alloc();
    wasm.__wbindgen_externrefs.set(idx, obj);
    return idx;
}

function getArrayU8FromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return getUint8ArrayMemory0().subarray(ptr / 1, ptr / 1 + len);
}

function getStringFromWasm0(ptr, len) {
    ptr = ptr >>> 0;
    return decodeText(getUint8ArrayMemory0().subarray(ptr, ptr + len));
}

let cachedUint8ArrayMemory0 = null;
function getUint8ArrayMemory0() {
    if (cachedUint8ArrayMemory0 === null || cachedUint8ArrayMemory0.byteLength === 0) {
        cachedUint8ArrayMemory0 = new Uint8Array(wasm.memory.buffer);
    }
    return cachedUint8ArrayMemory0;
}

function handleError(f, args) {
    try {
        return f.apply(this, args);
    } catch (e) {
        const idx = addToExternrefTable0(e);
        wasm.__wbindgen_exn_store(idx);
    }
}

function isLikeNone(x) {
    return x === undefined || x === null;
}

function passStringToWasm0(arg, malloc, realloc) {
    if (realloc === undefined) {
        const buf = cachedTextEncoder.encode(arg);
        const ptr = malloc(buf.length, 1) >>> 0;
        getUint8ArrayMemory0().subarray(ptr, ptr + buf.length).set(buf);
        WASM_VECTOR_LEN = buf.length;
        return ptr;
    }

    let len = arg.length;
    let ptr = malloc(len, 1) >>> 0;

    const mem = getUint8ArrayMemory0();

    let offset = 0;

    for (; offset < len; offset++) {
        const code = arg.charCodeAt(offset);
        if (code > 0x7F) break;
        mem[ptr + offset] = code;
    }
    if (offset !== len) {
        if (offset !== 0) {
            arg = arg.slice(offset);
        }
        ptr = realloc(ptr, len, len = offset + arg.length * 3, 1) >>> 0;
        const view = getUint8ArrayMemory0().subarray(ptr + offset, ptr + len);
        const ret = cachedTextEncoder.encodeInto(arg, view);

        offset += ret.written;
        ptr = realloc(ptr, len, offset, 1) >>> 0;
    }

    WASM_VECTOR_LEN = offset;
    return ptr;
}

function takeFromExternrefTable0(idx) {
    const value = wasm.__wbindgen_externrefs.get(idx);
    wasm.__externref_table_dealloc(idx);
    return value;
}

let cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true });
cachedTextDecoder.decode();
const MAX_SAFARI_DECODE_BYTES = 2146435072;
let numBytesDecoded = 0;
function decodeText(bytes) {
    numBytesDecoded += bytes.length;
    if (numBytesDecoded >= MAX_SAFARI_DECODE_BYTES) {
        cachedTextDecoder = new TextDecoder('utf-8', { ignoreBOM: true });
        cachedTextDecoder.decode();
        numBytesDecoded = bytes.length;
    }
    return cachedTextDecoder.decode(bytes);
}

const cachedTextEncoder = new TextEncoder();

if (!('encodeInto' in cachedTextEncoder)) {
    cachedTextEncoder.encodeInto = function (arg, view) {
        const buf = cachedTextEncoder.encode(arg);
        view.set(buf);
        return {
            read: arg.length,
            written: buf.length
        };
    };
}

let WASM_VECTOR_LEN = 0;

let wasmModule, wasmInstance, wasm;
function __wbg_finalize_init(instance, module) {
    wasmInstance = instance;
    wasm = instance.exports;
    wasmModule = module;
    cachedUint8ArrayMemory0 = null;
    wasm.__wbindgen_start();
    return wasm;
}

async function __wbg_load(module, imports) {
    if (typeof Response === 'function' && module instanceof Response) {
        if (!module.ok) {
            throw new Error(`failed to fetch Wasm: ${module.status} ${module.statusText} fetching '${module.url}'`);
        }

        if (typeof WebAssembly.instantiateStreaming === 'function') {
            try {
                return await WebAssembly.instantiateStreaming(module, imports);
            } catch (e) {
                const validResponse = expectedResponseType(module.type);

                if (validResponse && module.headers.get('Content-Type') !== 'application/wasm') {
                    console.warn("`WebAssembly.instantiateStreaming` failed because your server does not serve Wasm with `application/wasm` MIME type. Falling back to `WebAssembly.instantiate` which is slower. Original error:\n", e);

                } else { throw e; }
            }
        }

        const bytes = await module.arrayBuffer();
        return await WebAssembly.instantiate(bytes, imports);
    } else {
        const instance = await WebAssembly.instantiate(module, imports);

        if (instance instanceof WebAssembly.Instance) {
            return { instance, module };
        } else {
            return instance;
        }
    }

    function expectedResponseType(type) {
        switch (type) {
            case 'basic': case 'cors': case 'default': return true;
        }
        return false;
    }
}

function initSync(module) {
    if (wasm !== undefined) return wasm;


    if (module !== undefined) {
        if (Object.getPrototypeOf(module) === Object.prototype) {
            ({module} = module)
        } else {
            console.warn('using deprecated parameters for `initSync()`; pass a single object instead')
        }
    }

    const imports = __wbg_get_imports();
    if (!(module instanceof WebAssembly.Module)) {
        module = new WebAssembly.Module(module);
    }
    const instance = new WebAssembly.Instance(module, imports);
    return __wbg_finalize_init(instance, module);
}

let __wbg_init_promise;
async function __wbg_init(module_or_path) {
    if (wasm !== undefined) return wasm;
    if (__wbg_init_promise === undefined) {
        __wbg_init_promise = __wbg_init_once(module_or_path);
        __wbg_init_promise.catch(() => { __wbg_init_promise = undefined; });
    }
    return __wbg_init_promise;
}

async function __wbg_init_once(module_or_path) {

    if (module_or_path !== undefined) {
        if (Object.getPrototypeOf(module_or_path) === Object.prototype) {
            ({module_or_path} = module_or_path)
        } else {
            console.warn('using deprecated parameters for the initialization function; pass a single object instead')
        }
    }

    if (module_or_path === undefined) {
        module_or_path = new URL('friday_pos_engine_bg.wasm', import.meta.url);
    }
    const imports = __wbg_get_imports();

    if (typeof module_or_path === 'string' || (typeof Request === 'function' && module_or_path instanceof Request) || (typeof URL === 'function' && module_or_path instanceof URL)) {
        module_or_path = fetch(module_or_path);
    }

    const { instance, module } = await __wbg_load(await module_or_path, imports);

    return __wbg_finalize_init(instance, module);
}

export { initSync, __wbg_init as default };
