$(function() {
  var n_data_column = {};
  var data_column_selector = '[data-column]'
  $(data_column_selector).click(function() {
    var data_column = $(this).attr('data-column')
    var class_value = $(this).attr('class').split(' ').find(el => el.startsWith('progress-bar-'))
    var rows = $('[data-column="' + data_column + '"').not('.' + class_value).closest('tr')
    n_data_column[data_column] = 1 - (n_data_column[data_column] || 0)

    var header_class = 'text-' + class_value.split('-').pop()
    var column_index = $(this).closest('td').index()
    var header_selector = '#resources th:eq(' + column_index + ')'
    if (n_data_column[data_column]) {
      $(header_selector).addClass(header_class)
      update_urls_params({[data_column]: class_value == 'progress-bar-success'? 'on' : 'off'})
    } else {
      $(header_selector).attr('class').split(' ')
        .filter(el => el.startsWith('text-'))
        .forEach(el => $(header_selector).removeClass(el))
      update_urls_params({[data_column]: undefined})
    }

    var count_delta = n_data_column[data_column]? 1 : -1
    rows
      .each((_, el) => $(el).attr('data-count', parseInt($(el).attr('data-count') || '0') + count_delta))
      .each((_, el) => $(el).attr('data-count') == '0'? $(el).show() : $(el).hide())
  })
  var avg_width = $(data_column_selector).parent().toArray().reduce((partial_sum, el) => partial_sum + $(el).width(), 0) / $(data_column_selector).length
  $(data_column_selector).parent().each(function () { $(this).width(avg_width); })


  var url = new URL(window.location.href)
  $('tr:nth(1) ' + data_column_selector).each(function() {
    var data_column = $(this).attr('data-column')
    var column_status = url.searchParams.get(data_column)
    var class_value
    if (column_status == 'on') {
      class_value = 'progress-bar-success'
    } else if (column_status == 'off') {
      class_value = 'progress-bar-info'
    } else {
      return
    }
    var table_cell = $('.' + class_value + '[data-column="' + data_column + '"]').first()
    if (table_cell) {
      table_cell.click()
    }
  })
})
