$(function() {
  var n_data_column = {};
  var data_column_selector = '[data-column]'
  $(data_column_selector).click(function() {
    data_column = $(this).attr('data-column')
    class_value = $(this).attr('class').split(' ').find(el => el.startsWith('progress-bar-'))
    rows = $('[data-column="' + data_column + '"').not('.' + class_value).closest('tr')
    n_data_column[data_column] = 1 - (n_data_column[data_column] || 0)

    var header_class = 'text-' + class_value.split('-').pop()
    var column_index = $(this).closest('td').index()
    var header_selector = '#resources th:eq(' + column_index + ')'
    if (n_data_column[data_column]) {
      $(header_selector).addClass(header_class)
    } else {
      $(header_selector).attr('class').split(' ')
        .filter(el => el.startsWith('text-'))
        .forEach(el => $(header_selector).removeClass(el))
    }

    var count_delta = n_data_column[data_column]? 1 : -1
    rows
      .each((_, el) => $(el).attr('data-count', parseInt($(el).attr('data-count') || '0') + count_delta))
      .each((_, el) => $(el).attr('data-count') == '0'? $(el).show() : $(el).hide())
  })
  var max_width = Math.max(...$(data_column_selector).parent().map(function() { return $(this).width() }), 0)
  $(data_column_selector).parent().each(function () { $(this).width(max_width); })
})
