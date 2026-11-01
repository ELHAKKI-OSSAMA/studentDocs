import { StudentView } from "./view";

// One page per student id: rendered on request, never prerendered.
export const instant = false;

/** Server entry: resolves the route parameter, the student is loaded client-side with the session. */
export default async function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <StudentView id={id} />;
}
