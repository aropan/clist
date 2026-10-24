# FullCalendar 7.1.1

The Standard Bundle and Classic theme are vendored from the `fullcalendar@7.1.1`
npm package, with the MIT license in `LICENSE.md`.

The distribution contains unminified assets. These local copies use jsDelivr's
minified versions (Terser 5.48.0 for JavaScript, clean-css 5.3.3 for CSS):

- https://cdn.jsdelivr.net/npm/fullcalendar@7.1.1/all/global.min.js
- https://cdn.jsdelivr.net/npm/fullcalendar@7.1.1/themes/classic/global.min.js
- https://cdn.jsdelivr.net/npm/fullcalendar@7.1.1/skeleton.min.css
- https://cdn.jsdelivr.net/npm/fullcalendar@7.1.1/themes/classic/theme.min.css
- https://cdn.jsdelivr.net/npm/fullcalendar@7.1.1/themes/classic/palette.min.css

Source map comments are removed because the maps are not vendored. Copyright
and minifier headers are preserved. Assets are served locally through Django
static files; jsDelivr is only used when updating the vendored copies.
