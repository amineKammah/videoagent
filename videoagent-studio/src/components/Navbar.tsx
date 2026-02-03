'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { UserCompanySelector } from './UserCompanySelector';

export function Navbar() {
    const pathname = usePathname();

    const navItems = [
        { name: 'Customers', href: '/customers' },
        { name: 'Videos', href: '/studio' },
        { name: 'Insights', href: '/insights' },
    ];

    return (
        <nav className="border-b border-gray-200 bg-white">
            <div className="mx-auto px-4 sm:px-6 lg:px-8">
                <div className="flex h-16 justify-between">
                    <div className="flex">
                        <div className="flex flex-shrink-0 items-center">
                            <span className="text-xl font-bold text-gray-900">VideoAgent</span>
                        </div>
                        <div className="hidden sm:ml-6 sm:flex sm:space-x-8">
                            {navItems.map((item) => {
                                const isActive = pathname.startsWith(item.href);
                                return (
                                    <Link
                                        key={item.name}
                                        href={item.href}
                                        className={`inline-flex items-center border-b-2 px-1 pt-1 text-sm font-medium ${isActive
                                            ? 'border-indigo-500 text-gray-900'
                                            : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
                                            }`}
                                    >
                                        {item.name}
                                    </Link>
                                );
                            })}
                        </div>
                    </div>
                    {/* Right side: User/Company Selector */}
                    <div className="flex items-center">
                        <UserCompanySelector />
                    </div>
                </div>
            </div>
        </nav>
    );
}
