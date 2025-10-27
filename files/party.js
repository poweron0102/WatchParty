const sidebar = document.getElementById('sidebar');
const toggleBtn = document.getElementById('sidebar-toggle');

toggleBtn.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
    if (sidebar.classList.contains('collapsed')) {
        toggleBtn.innerHTML = '<';
        toggleBtn.title = 'Expandir chat';
    } else {
        toggleBtn.innerHTML = '>';
        toggleBtn.title = 'Recolher chat';
    }
});
