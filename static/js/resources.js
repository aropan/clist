$(function() {
  var n_data_column = {};
  $('[data-column]').click(function() {
    data_column = $(this).attr('data-column')
    class_value = $(this).attr('class').split(' ').find(el => el.startsWith('progress-bar-'))
    rows = $('[data-column="' + data_column + '"').not('.' + class_value).closest('tr')
    n_data_column[data_column] = 1 - (n_data_column[data_column] || 0)
    if (n_data_column[data_column]) {
      rows.hide()
    } else {
      rows.show()
    }
  })
})
