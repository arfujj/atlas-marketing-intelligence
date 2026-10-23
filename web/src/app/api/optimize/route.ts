import { API_URL } from "@/lib/api";

/** Same-origin proxy so the browser never needs the API's address or CORS. */
export async function POST(req: Request) {
  const res = await fetch(new URL("/halden/optimize", API_URL), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: await req.text(),
    cache: "no-store",
  });
  return new Response(res.body, { status: res.status, headers: { "content-type": "application/json" } });
}
