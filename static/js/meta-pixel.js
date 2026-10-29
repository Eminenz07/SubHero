/**
 * Meta Pixel Conversion Event Utilities
 * =====================================
 * Provides functions to fire standard Meta Pixel conversion events.
 * Only fires when Meta Pixel is loaded (meta_pixel_id is configured).
 *
 * Events follow Meta's standard naming and parameter conventions:
 * https://developers.facebook.com/docs/meta-pixel/implementation/conversion-tracking
 */

(function() {
    'use strict';

    // Check if Meta Pixel is initialized
    function isPixelReady() {
        return typeof window.fbq === 'function' && window.fbq.loaded;
    }

    // Safe wrapper to fire events
    function track(eventName, parameters) {
        if (!isPixelReady()) {
            console.debug('[Meta Pixel] Not ready, skipping event:', eventName);
            return;
        }

        try {
            fbq('track', eventName, parameters);
            console.debug('[Meta Pixel] Event fired:', eventName, parameters);
        } catch (e) {
            console.warn('[Meta Pixel] Error firing event:', eventName, e);
        }
    }

    /**
     * Track CompleteRegistration
     * Fired when a user completes registration (email verified + PIN set)
     * @param {string} method - 'email' or 'phone'
     */
    window.SubHeroPixel = window.SubHeroPixel || {};
    window.SubHeroPixel.trackCompleteRegistration = function(method) {
        track('CompleteRegistration', {
            registration_method: method || 'email'
        });
    };

    /**
     * Track Purchase
     * Fired when a wallet funding is confirmed
     * @param {number} value - Amount in NGN (kobo converted to naira)
     * @param {string} currency - Currency code (always 'NGN')
     * @param {string} transactionRef - Internal transaction reference
     */
    window.SubHeroPixel.trackPurchase = function(value, currency, transactionRef) {
        track('Purchase', {
            value: Number(value) || 0,
            currency: currency || 'NGN',
            transaction_id: transactionRef || ''
        });
    };

    /**
     * Track Lead
     * Fired when a user creates their first giveaway
     * @param {string} giveawayId - Internal giveaway ID/slug
     * @param {string} giveawayType - 'DATA' or 'AIRTIME'
     */
    window.SubHeroPixel.trackLead = function(giveawayId, giveawayType) {
        track('Lead', {
            content_name: 'Giveaway Creation',
            content_category: 'Giveaway',
            content_ids: [giveawayId || ''],
            content_type: 'giveaway',
            giveaway_type: giveawayType || ''
        });
    };

    /**
     * Track InitiateCheckout
     * Fired when a user opens the wallet funding flow
     * @param {number} value - Amount in NGN (if specified)
     * @param {string} currency - Currency code (always 'NGN')
     * @param {string} fundingMethod - 'card', 'bank_transfer', 'ussd', etc.
     */
    window.SubHeroPixel.trackInitiateCheckout = function(value, currency, fundingMethod) {
        track('InitiateCheckout', {
            value: Number(value) || 0,
            currency: currency || 'NGN',
            funding_method: fundingMethod || ''
        });
    };

    /**
     * Track AddPaymentInfo
     * Fired when user adds/updates payment info (e.g., virtual account)
     */
    window.SubHeroPixel.trackAddPaymentInfo = function(paymentMethod) {
        track('AddPaymentInfo', {
            payment_method: paymentMethod || 'bank_transfer'
        });
    };

    /**
     * Track custom event
     * For any other custom tracking needs
     */
    window.SubHeroPixel.trackCustom = function(eventName, parameters) {
        track(eventName, parameters);
    };

    // Auto-fire InitiateCheckout on wallet funding page load
    document.addEventListener('DOMContentLoaded', function() {
        // Check if we're on the wallet funding page
        if (window.location.pathname === '/wallet/fund/' || window.location.pathname.startsWith('/wallet/fund')) {
            // Fire InitiateCheckout with 0 value (user hasn't entered amount yet)
            // We'll fire again with actual value when they proceed
            window.SubHeroPixel.trackInitiateCheckout(0, 'NGN', 'page_load');
        }
    });

    // Listen for HTMX events to fire events on dynamic content
    document.body.addEventListener('htmx:afterSwap', function(evt) {
        // Check if wallet funding page was loaded via HTMX
        if (evt.detail.target && evt.detail.target.id === 'smm-cards-container') {
            // SMM page - no specific pixel event needed
        }
    });

})();