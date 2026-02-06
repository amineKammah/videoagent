import { redirect } from 'next/navigation';

type HomePageProps = {
  searchParams?: Promise<Record<string, string | string[] | undefined>> | Record<string, string | string[] | undefined>;
};

export default async function Home({ searchParams }: HomePageProps) {
  const resolvedSearchParams = await searchParams;
  const query = new URLSearchParams();

  for (const [key, value] of Object.entries(resolvedSearchParams ?? {})) {
    if (Array.isArray(value)) {
      value.forEach((entry) => query.append(key, entry));
      continue;
    }
    if (typeof value === 'string') {
      query.set(key, value);
    }
  }

  const queryString = query.toString();
  redirect(queryString ? `/studio?${queryString}` : '/studio');
}
