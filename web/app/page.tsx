import Link from "next/link";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col justify-center gap-6 px-5 py-16">
      <h1 className="text-3xl font-semibold">Your Nuri plan</h1>
      <p className="text-ink/70">
        A few questions about your goals, body and how you like to eat, then the targets we set
        for you and why.
      </p>
      <Link
        href="/onboarding"
        className="self-start rounded-full bg-signal px-6 py-2.5 text-sm font-medium text-white"
      >
        Get started
      </Link>
    </main>
  );
}
