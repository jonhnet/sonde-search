---
---
/**
 * SondeSearch API Client Library
 *
 * Provides a consistent interface for calling the SondeSearch backend API
 * with automatic dev/prod URL selection.
 */

(function(window) {
    'use strict';

    /**
     * SondeSearch API client configuration and helper functions
     */
    var SondeSearchAPI = {
        /**
         * Get the base URL for API requests.
         * Automatically selects dev or prod based on Jekyll site.dev_mode variable.
         *
         * @returns {string} The base URL for API requests
         */
        getBaseUrl: function() {
            // This will be replaced by Jekyll during build
            // In dev mode (site.dev_mode == 1), use localhost
            // In prod mode, use production API
            {% if site.dev_mode == 1 %}
            return 'http://localhost:4001/';
            {% else %}
            return 'https://api.sondesearch.lectrobox.com/api/v2/';
            {% endif %}
        },

        /**
         * Build a full URL for an API endpoint
         *
         * @param {string} endpoint - The API endpoint path (e.g., 'get_config', 'subscribe')
         * @returns {string} The full URL
         */
        buildUrl: function(endpoint) {
            var baseUrl = this.getBaseUrl();
            // Remove leading slash from endpoint if present
            if (endpoint.startsWith('/')) {
                endpoint = endpoint.substring(1);
            }
            return baseUrl + endpoint;
        },

        /**
         * Make a GET request to the API and return JSON
         *
         * @param {string} endpoint - The API endpoint
         * @param {Object} options - Optional fetch options (headers, credentials, etc.)
         * @returns {Promise<Object>} Promise that resolves to JSON object
         */
        get: function(endpoint, options) {
            options = options || {};
            options.method = 'GET';
            return fetch(this.buildUrl(endpoint), options).then(function(response) {
                if (!response.ok) {
                    throw new Error('API request failed: ' + response.statusText);
                }
                return response.json();
            });
        },

        /**
         * Make a POST request to the API and return JSON
         *
         * @param {string} endpoint - The API endpoint
         * @param {Object} data - Data to send (will be converted to FormData if object)
         * @param {Object} options - Optional fetch options
         * @returns {Promise<Object>} Promise that resolves to JSON object
         */
        post: function(endpoint, data, options) {
            options = options || {};
            options.method = 'POST';

            // Convert plain object to FormData if needed
            if (data && !(data instanceof FormData)) {
                var formData = new FormData();
                for (var key in data) {
                    if (data.hasOwnProperty(key)) {
                        formData.append(key, data[key]);
                    }
                }
                options.body = formData;
            } else if (data) {
                options.body = data;
            }

            return fetch(this.buildUrl(endpoint), options).then(function(response) {
                if (!response.ok) {
                    throw new Error('API request failed: ' + response.statusText);
                }
                return response.json();
            });
        },

        /**
         * jQuery-style AJAX wrapper for backward compatibility
         *
         * @param {Object} config - jQuery-style AJAX configuration
         * @returns {jqXHR} jQuery AJAX promise
         */
        ajax: function(config) {
            if (typeof $ === 'undefined' || !$.ajax) {
                throw new Error('jQuery is required for ajax() method');
            }

            // Build full URL
            config.url = this.buildUrl(config.url || config.endpoint);

            // Use jQuery's ajax
            return $.ajax(config);
        }
    };

    // Export to window
    window.SondeSearchAPI = SondeSearchAPI;

})(window);
