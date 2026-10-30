import { EmailCaseView } from "./view";

// One page per email case: rendered on request, never prerendered.
export const instant = false;

/** Server entry: resolves the route parameter, the case itself is loaded client-side with the session. */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <EmailCaseView id={id} />;
}
