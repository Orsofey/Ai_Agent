const site = decodeURIComponent(location.hash.slice(1));
if (site) document.getElementById('site').textContent = site + ' заблокирован';
