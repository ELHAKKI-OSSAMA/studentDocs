import { RequestView } from "./view";

// One page per request id: rendered on request, never prerendered.
export const instant = false;

/** Server entry: resolves the route parameter, the request itself is loaded client-side with the session. */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RequestView id={id} />;
}
