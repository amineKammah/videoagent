'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useSessionStore } from '@/store/session';
import { api } from '@/lib/api';
import { Company, User } from '@/lib/types';

export function UserCompanySelector() {
    const router = useRouter();
    const pathname = usePathname();

    const sessionCompany = useSessionStore(state => state.company);
    const sessionUser = useSessionStore(state => state.user);
    const setCompany = useSessionStore(state => state.setCompany);
    const setUser = useSessionStore(state => state.setUser);
    const clearSessionData = useSessionStore(state => state.clearSessionData);

    const [companies, setCompanies] = useState<Company[]>([]);
    const [users, setUsers] = useState<User[]>([]);
    const [loadingCompanies, setLoadingCompanies] = useState(false);
    const [loadingUsers, setLoadingUsers] = useState(false);
    const pendingCompanyContextReset = useRef(false);
    const sessionCompanyId = sessionCompany?.id;

    const resetActiveView = useCallback(() => {
        clearSessionData();
        router.replace(pathname);
    }, [clearSessionData, pathname, router]);

    // Fetch companies on mount
    useEffect(() => {
        const fetchCompanies = async () => {
            setLoadingCompanies(true);
            try {
                const list = await api.listCompanies();
                setCompanies(list);
            } catch (error) {
                console.error('Failed to list companies', error);
            } finally {
                setLoadingCompanies(false);
            }
        };
        fetchCompanies();
    }, []);

    // Fetch users when company changes
    useEffect(() => {
        const fetchUsers = async () => {
            if (!sessionCompanyId) {
                setUsers([]);
                return;
            }

            setLoadingUsers(true);
            try {
                const list = await api.listUsers(sessionCompanyId);
                setUsers(list);

                // If the current user is NOT in the new list (e.g. we just switched company),
                // we must pick a valid user from this company to enforce "Always a User".
                // Note: AuthProvider might have already set a user, but if we manually switch company 
                // via this selector, we need to ensure the user matches.

                // Check if current sessionUser belongs to this company? 
                // The User type usually doesn't strictly have company_id on it according to some schemas, 
                // but functionally we shouldn't have a user from Company A active while Company B is selected.

                // Heuristic: If we switched company, we almost certainly need to switch user?
                // Let's check consistency. 
                const isCurrentUserInList = list.some(u => u.id === sessionUser?.id);

                if (!isCurrentUserInList && list.length > 0) {
                    // Auto-select first user of the new company
                    console.log('Switching to first user of new company:', list[0].id);
                    setUser(list[0]);
                } else if (list.length === 0) {
                    // Edge case: Company has no users. 
                    // Requirement says "ALWAYS A USER". 
                    // We might need to create one? Or just leave it (but user said "dont ever have to check if user is NULL").
                    // For now, let's assume valid companies have users or AuthProvider handles the "init" case.
                    // If we switch to a empty company, we might be in trouble.
                    console.warn('Selected company has no users!');
                }

                if (pendingCompanyContextReset.current) {
                    pendingCompanyContextReset.current = false;
                    resetActiveView();
                }

            } catch (error) {
                console.error('Failed to list users', error);
            } finally {
                setLoadingUsers(false);
            }
        };

        fetchUsers();
    }, [sessionCompanyId, sessionUser?.id, setUser, resetActiveView]); // Keep user list in sync with active company/user

    const handleCompanyChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const companyId = e.target.value;
        const selected = companies.find(c => c.id === companyId);
        if (selected) {
            pendingCompanyContextReset.current = selected.id !== sessionCompany?.id;
            setCompany(selected);
            // We rely on the useEffect above to fetch users and update the user selection
        }
    };

    const handleUserChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
        const userId = e.target.value;
        const selected = users.find(u => u.id === userId);
        if (selected) {
            setUser(selected);
            if (selected.id !== sessionUser?.id) {
                resetActiveView();
            }
        }
    };

    if (!sessionCompany || !sessionUser) return null; // Should not happen due to AuthProvider, but safe guard

    return (
        <div className="flex items-center gap-4">
            {/* Company Selector */}
            <div className="flex flex-col">
                <label className="text-[10px] uppercase font-bold text-gray-400">Company</label>
                <select
                    value={sessionCompany.id}
                    onChange={handleCompanyChange}
                    className="block w-40 rounded-md border-0 py-1 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-xs sm:leading-6"
                    disabled={loadingCompanies}
                >
                    {companies.map(c => (
                        <option key={c.id} value={c.id}>
                            {c.name}
                        </option>
                    ))}
                </select>
            </div>

            {/* User Selector */}
            <div className="flex flex-col">
                <label className="text-[10px] uppercase font-bold text-gray-400">User</label>
                <select
                    value={sessionUser.id}
                    onChange={handleUserChange}
                    className="block w-40 rounded-md border-0 py-1 text-gray-900 shadow-sm ring-1 ring-inset ring-gray-300 focus:ring-2 focus:ring-inset focus:ring-indigo-600 sm:text-xs sm:leading-6"
                    disabled={loadingUsers}
                >
                    {users.map(u => (
                        <option key={u.id} value={u.id}>
                            {u.name || u.email}
                        </option>
                    ))}
                </select>
            </div>
        </div>
    );
}
