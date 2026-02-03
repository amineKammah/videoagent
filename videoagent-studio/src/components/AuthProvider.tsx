'use client';

import { useEffect, useRef, useState } from 'react';
import { useSessionStore } from '@/store/session';
import { api, ApiUtils } from '@/lib/api';

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const apiHealthy = useSessionStore(state => state.apiHealthy);
    const checkHealth = useSessionStore(state => state.checkHealth);
    const user = useSessionStore(state => state.user);
    const company = useSessionStore(state => state.company);

    // Bootstrapping state
    // We are bootstrapping if we haven't finished loading user/company yet.
    // Start as NOT bootstrapped.
    const hasBootstrapped = useRef(false);
    const [isBootstrapping, setIsBootstrapping] = useState(true);

    // 1. Health Check Loop
    useEffect(() => {
        // Initial check
        checkHealth();

        // Poll every 5s (more frequent than 10s is better for initial load)
        const interval = setInterval(checkHealth, 5000);
        return () => clearInterval(interval);
    }, [checkHealth]);

    // 2. Sync user ID to API client whenever it changes
    useEffect(() => {
        if (user) {
            ApiUtils.currentUserId = user.id;
        } else {
            ApiUtils.currentUserId = null;
        }
    }, [user]);

    // 3. Sync company ID to API client whenever it changes
    useEffect(() => {
        if (company) {
            ApiUtils.currentCompanyId = company.id;
        } else {
            ApiUtils.currentCompanyId = null;
        }
    }, [company]);

    // 4. Bootstrap User Context when API is healthy
    useEffect(() => {
        if (apiHealthy && !hasBootstrapped.current) {
            bootstrapUserContext();
        }
    }, [apiHealthy]);

    const bootstrapUserContext = async () => {
        try {
            hasBootstrapped.current = true;
            console.log('Bootstrapping user context...');

            // check if we have persisted state
            const currentCompany = useSessionStore.getState().company;
            const currentUser = useSessionStore.getState().user;

            if (currentCompany && currentUser) {
                console.log('Restoring persisted session:', currentCompany.id, currentUser.id);
                // Just sync utils immediately to be safe
                ApiUtils.currentUserId = currentUser.id;
                ApiUtils.currentCompanyId = currentCompany.id;

                setIsBootstrapping(false);
                return;
            }

            // 1. Get Company
            const companies = await api.listCompanies();
            let targetCompany = companies[0];
            if (!targetCompany) {
                // If no companies exist, creating one is a safe default for this "single-tenant-ish" local app
                targetCompany = await api.createCompany('Default Company');
            }
            useSessionStore.getState().setCompany(targetCompany);
            console.log('Company set:', targetCompany.id);

            // 2. Get User
            const users = await api.listUsers(targetCompany.id);
            let targetUser = users[0];
            if (!targetUser) {
                targetUser = await api.createUser(targetCompany.id, 'user@example.com', 'Default User');
            }
            useSessionStore.getState().setUser(targetUser);
            console.log('User set:', targetUser.id);

            // Sync with API client explicitly (useEffect might lag slightly)
            ApiUtils.currentUserId = targetUser.id;
            ApiUtils.currentCompanyId = targetCompany.id;

            console.log('User context fully bootstrapped.');

            // Mark as done
            setIsBootstrapping(false);
        } catch (error) {
            console.error('Failed to bootstrap user context:', error);
            // If failed, we might want to retry later or show error.
            // Resetting hasBootstrapped allows retry if apiHealthy toggles or component remounts
            hasBootstrapped.current = false;

            // Retry automatically after delay
            setTimeout(() => {
                if (apiHealthy && !hasBootstrapped.current) {
                    bootstrapUserContext();
                }
            }, 5000);
        }
    };

    // If still bootstrapping or NO user/company, show loading
    // We strictly require user and company to be present.
    if (isBootstrapping || !user || !company) {
        return (
            <div className="flex h-screen w-screen items-center justify-center bg-[#f8fafc]">
                <div className="flex flex-col items-center gap-4">
                    {/* Simple spinner */}
                    <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-200 border-t-teal-600"></div>
                    <p className="text-sm font-medium text-slate-600 animate-pulse">
                        {apiHealthy ? 'Loading your workspace...' : 'Connecting to server...'}
                    </p>
                </div>
            </div>
        );
    }

    return <>{children}</>;
}
