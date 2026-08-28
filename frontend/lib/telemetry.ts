import { context, propagation, type Context, SpanKind, SpanStatusCode, trace } from "@opentelemetry/api";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { resourceFromAttributes } from "@opentelemetry/resources";
import { BatchSpanProcessor, NodeTracerProvider, type ReadableSpan, type Span, type SpanProcessor } from "@opentelemetry/sdk-trace-node";

const globalState = globalThis as typeof globalThis & { __ragTracerProvider?: NodeTracerProvider };

class AllowlistedSpanProcessor implements SpanProcessor {
  constructor(private readonly delegate: SpanProcessor) {}
  onStart(span: Span, parentContext: Context): void {
    if (span.name === "bff.backend.request") this.delegate.onStart(span, parentContext);
  }
  onEnd(span: ReadableSpan): void {
    if (span.name === "bff.backend.request") this.delegate.onEnd(span);
  }
  shutdown(): Promise<void> { return this.delegate.shutdown(); }
  forceFlush(): Promise<void> { return this.delegate.forceFlush(); }
}

export function initializeTelemetry() {
  if (globalState.__ragTracerProvider || process.env.TELEMETRY_ENABLED !== "true") return;
  const endpoint = `${(process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://otel-collector:4318").replace(/\/$/, "")}/v1/traces`;
  const provider = new NodeTracerProvider({
    resource: resourceFromAttributes({ "service.name": "rag-frontend" }),
    spanProcessors: [new AllowlistedSpanProcessor(new BatchSpanProcessor(new OTLPTraceExporter({ url: endpoint })))],
  });
  provider.register();
  globalState.__ragTracerProvider = provider;
}

export async function bffSpan<T>(operation: () => Promise<T>): Promise<T> {
  initializeTelemetry();
  const tracer = trace.getTracer("production-rag-assistant-frontend");
  return tracer.startActiveSpan("bff.backend.request", { kind: SpanKind.SERVER, attributes: { "http.route": "/api/backend/{path}" } }, async span => {
    try { return await operation(); }
    catch (error) { span.setStatus({ code: SpanStatusCode.ERROR }); throw error; }
    finally { span.end(); }
  });
}

export function injectTrace(headers: Headers): void {
  const carrier: Record<string, string> = {};
  propagation.inject(context.active(), carrier);
  for (const [key, value] of Object.entries(carrier)) headers.set(key, value);
}
