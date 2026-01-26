'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { Customer } from '@/lib/types';

export default function CustomersPage() {
    const [customers, setCustomers] = useState<Customer[]>([]);
    const [loading, setLoading] = useState(true);
    const [selectedCustomer, setSelectedCustomer] = useState<Customer | null>(null);

    useEffect(() => {
        loadCustomers();
    }, []);

    async function loadCustomers() {
        try {
            const data = await api.getCustomers();
            setCustomers(data);
        } catch (error) {
            console.error("Failed to load customers:", error);
        } finally {
            setLoading(false);
        }
    }

    if (loading) {
        return <div className="p-8 text-center text-gray-500">Loading customers...</div>;
    }

    return (
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
            <div className="space-y-6">
                <header>
                    <h1 className="text-3xl font-bold leading-tight tracking-tight text-gray-900">Customers</h1>
                    <p className="mt-1 text-sm text-gray-500">
                        Manage and view your customer personas.
                    </p>
                </header>

                <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow">
                    <table className="min-w-full divide-y divide-gray-200">
                        <thead className="bg-gray-50">
                            <tr>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Name</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Title</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Company</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Industry</th>
                                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">Size</th>
                            </tr>
                        </thead>
                        <tbody className="bg-white divide-y divide-gray-200">
                            {customers.map((customer) => (
                                <tr
                                    key={customer.id}
                                    onClick={() => setSelectedCustomer(customer)}
                                    className="hover:bg-gray-50 cursor-pointer transition-colors"
                                >
                                    <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">{customer.name}</td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{customer.title}</td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{customer.company}</td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{customer.industry}</td>
                                    <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">{customer.company_size}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {selectedCustomer && (
                    <CustomerModal
                        customer={selectedCustomer}
                        onClose={() => setSelectedCustomer(null)}
                    />
                )}
            </div>
        </main>
    );
}

function CustomerModal({ customer, onClose }: { customer: Customer; onClose: () => void }) {
    const router = useRouter();

    const handleGenerateVideo = () => {
        // Format prompt for LLM with ALL details
        let prompt = "Create a video for this customer with the following details:\n\n";

        Object.entries(customer).forEach(([key, value]) => {
            // Skip internal IDs if preferred, or include them. 
            // User said "literally all details", but raw IDs are rarely useful for the LLM's creative process.
            // I'll skip 'id' and 'brand_id' to keep it clean but useful.
            if (key === 'id' || key === 'brand_id') return;

            // Format key for readability
            const label = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
            prompt += `${label}: ${value}\n`;
        });

        const encodedPrompt = encodeURIComponent(prompt.trim());
        router.push(`/studio?initialMessage=${encodedPrompt}`);
    };

    return (
        <div className="fixed inset-0 z-50 overflow-y-auto" aria-labelledby="modal-title" role="dialog" aria-modal="true">
            <div className="flex min-h-screen items-end justify-center px-4 pt-4 pb-20 text-center sm:block sm:p-0">

                {/* Background overlay with blur */}
                <div
                    className="fixed inset-0 bg-gray-500/75 backdrop-blur-sm transition-opacity"
                    aria-hidden="true"
                    onClick={onClose}
                ></div>

                {/* Centering trick */}
                <span className="hidden sm:inline-block sm:h-screen sm:align-middle" aria-hidden="true">&#8203;</span>

                {/* Modal Panel */}
                <div className="relative inline-block transform overflow-hidden rounded-lg bg-white text-left align-bottom shadow-xl transition-all sm:my-8 sm:w-full sm:max-w-3xl sm:align-middle">

                    {/* Header */}
                    <div className="bg-white px-4 pt-5 pb-4 sm:p-6 sm:pb-4 border-b border-gray-200">
                        <div className="flex items-start justify-between">
                            <div>
                                <h3 className="text-xl font-semibold leading-6 text-gray-900" id="modal-title">
                                    {customer.name}
                                </h3>
                                <p className="mt-1 text-sm text-gray-500">{customer.title} at {customer.company}</p>
                            </div>
                            <button
                                type="button"
                                className="rounded-md bg-white text-gray-400 hover:text-gray-500 focus:outline-none"
                                onClick={onClose}
                            >
                                <span className="sr-only">Close</span>
                                <svg className="h-6 w-6" fill="none" viewBox="0 0 24 24" strokeWidth="1.5" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    </div>

                    {/* Content */}
                    <div className="px-4 py-5 sm:p-6">
                        <dl className="grid grid-cols-1 gap-x-6 gap-y-8 sm:grid-cols-2">
                            {/* CTA - Spans full width */}
                            <div className="sm:col-span-2">
                                <button
                                    onClick={handleGenerateVideo}
                                    className="w-full inline-flex justify-center items-center px-4 py-3 border border-transparent shadow-sm text-sm font-medium rounded-lg text-white bg-indigo-600 hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 transition-colors"
                                >
                                    <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5 mr-2" viewBox="0 0 20 20" fill="currentColor">
                                        <path d="M2 6a2 2 0 012-2h6a2 2 0 012 2v8a2 2 0 01-2 2H4a2 2 0 01-2-2V6zM14.553 7.106A1 1 0 0014 8v4a1 1 0 00.553.894l2 1A1 1 0 0018 13V7a1 1 0 00-1.447-.894l-2 1z" />
                                    </svg>
                                    Generate Video for {customer.name}
                                </button>
                            </div>

                            {Object.entries(customer).map(([key, value]) => {
                                if (key === 'id' || key === 'brand_id' || key === 'name' || key === 'title' || key === 'company') return null;
                                // Make long text fields span full width
                                const isLongText = typeof value === 'string' && value.length > 50;
                                return (
                                    <div key={key} className={isLongText ? "sm:col-span-2" : "sm:col-span-1"}>
                                        <dt className="text-sm font-medium text-gray-500 capitalize">
                                            {key.replace(/_/g, ' ')}
                                        </dt>
                                        <dd className="mt-1 text-sm text-gray-900 rounded-md bg-gray-50 p-3 border border-gray-100">
                                            {value}
                                        </dd>
                                    </div>
                                );
                            })}
                        </dl>
                    </div>
                </div>
            </div>
        </div>
    );
}
