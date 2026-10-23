import { API_URL } from "@/lib/api";

export async function GET() {
  const res = await fetch(new URL("/analyst/suggestions", API_URL), { cache: "no-store" });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}

export async function POST(req: Request) {
  const res = await fetch(new URL("/analyst", API_URL), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}
