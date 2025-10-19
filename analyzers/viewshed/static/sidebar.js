// Shared sidebar toggle functionality
(function() {
    let sidebarOpen = true;

    function toggleSidebar() {
        const sidebar = document.querySelector('.sidebar');

        sidebarOpen = !sidebarOpen;

        if (sidebarOpen) {
            sidebar.classList.remove('collapsed');
        } else {
            sidebar.classList.add('collapsed');
        }

        // Resize map after animation
        setTimeout(() => {
            const map = window.map || window.viewshedMap;
            if (map && map.invalidateSize) {
                map.invalidateSize();
            }
        }, 350);
    }

    // Make toggleSidebar available globally
    window.toggleSidebar = toggleSidebar;

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', function() {
        const toggleBtn = document.getElementById('toggle-sidebar');
        if (!toggleBtn) return;

        if (window.innerWidth <= 768) {
            // Mobile: sidebar collapsed
            const sidebar = document.querySelector('.sidebar');
            sidebar.classList.add('collapsed');
            sidebarOpen = false;
        }
        // On desktop, sidebar starts open
    });
})();
