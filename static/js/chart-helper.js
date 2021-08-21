function create_chart_config(resource_info, dates, y_field = 'new_rating', is_addition = false) {
  if (is_addition) {
    var values = [].concat.apply([], $.map(resource_info['data'], function(data, index) { return $.map(data, function(val) { return val['values'][y_field] }) }))
    var min_field = Math.min(...values)
    var max_field = Math.max(...values)
    if (min_field === undefined || max_field === undefined || min_field == max_field) {
      $.notify(
        'Skip ' + y_field + ' field, min value = ' + min_field + ', max value = ' + max_field,
        {position: 'bottom right', className: 'warn'},
      )
      return false;
    }
  } else {
    var min_rating = resource_info['min']
    var max_rating = resource_info['max']
    var rating_labels = new Set($.map(resource_info['colors'], function(val) { return val['low']; }))
    var max_rating_labels = Math.max(...$.map(resource_info['colors'], function(val) { return val['low']; }))
    var highest = resource_info['highest']
  }

  function get_or_default(value, other) {
    return value == undefined? other: value
  }

  var datasets_infos = get_or_default(resource_info['datasets'], {})
  var datasets_colors = get_or_default(datasets_infos['colors'], [])
  var datasets_labels = get_or_default(datasets_infos['labels'], [])
  var coloring_field = get_or_default(resource_info['coloring_field'], 'new_rating')
  var n_gen_y_axis_ticks = get_or_default(resource_info['n_gen_y_axis_ticks'], false)
  if (n_gen_y_axis_ticks) {
    var delta = Math.floor((max_rating - min_rating) / n_gen_y_axis_ticks)
    var power = Math.max(0, Math.floor(Math.log10(delta)) - 1)
    var div10 = Math.pow(10, power)
    var y_axis_ticks_every = Math.floor(delta / div10) * div10
  } else {
    var y_axis_ticks_every = false
  }
  var with_url = !get_or_default(resource_info['without_url'], false)


  var datasets = [].concat.apply([], $.map(resource_info['data'], function(data, index) {
    var dataset = {
      data: $.map(data, function(val) { return {x: val['date'], y: is_addition? val['values'][y_field] : val['new_rating']}; }),
      label: datasets_labels[index],
      labelIndex_: index,
      history: data,
      borderWidth: get_or_default(resource_info['border_width'], 1),
      borderColor: get_or_default(datasets_colors[index], 'black'),
      pointRadius: get_or_default(resource_info['point_radius'], 3),
      pointHitRadius: get_or_default(resource_info['point_hit_radius'], 1),
      pointHoverRadius: 5,
      fill: false,
      lineTension: 0,
      pointBackgroundColor: $.map(data, function(val) {
        for (var idx in resource_info['colors']) {
          var rating = resource_info['colors'][idx]
          if (rating['low'] <= val[coloring_field] && val[coloring_field] <= rating['high']) {
            return rating['hex_rgb']
          }
        }
      }),
    }
    var ret = [dataset]
    if (get_or_default(resource_info['outline'], false)) {
      var border = {...dataset, }
      border['borderWidth'] += 1
      border['borderColor'] = 'black'
      delete border['history']
      ret.push(border)
    }
    return ret
  }))

  return {
    type: 'line',
    data: {
      labels: dates,
      datasets: datasets,
    },
    plugins: [
      {
        beforeDraw: function (chart) {
          if (get_or_default(resource_info['without_before_draw'], false) || is_addition) {
            return
          }
          var rating_colors = resource_info['colors']
          var ctx = chart.ctx
          var y_axis = chart.scales["y"]
          var x_axis = chart.scales["x"]

          for (var i = 0; i < rating_colors.length; ++i) {
            var to = get_y_chart(rating_colors[i].low, y_axis)
            var from = get_y_chart(rating_colors[i].high + 1, y_axis)
            hsl = rating_colors[i].hsl
            color = 'hsl(' + hsl[0] * 360 + ',' + hsl[1] * 100 + '%,' + (hsl[2] * 100 + 100) * 0.5 + '%)'
            ctx.fillStyle = color
            ctx.fillRect(x_axis.left, from, x_axis.width, to - from)
          }

          if (highest) {
            var y = get_y_chart(highest['value'], y_axis)
            ctx.beginPath()
            ctx.setLineDash([5, 15])
            ctx.moveTo(x_axis.left, y)
            ctx.lineTo(x_axis.right, y)
            ctx.stroke()
            ctx.setLineDash([])
            ctx.closePath()
          }
        },
      },
      {
        beforeDatasetsDraw: function (chart) {
          if (get_or_default(resource_info['without_highest'], false) || !highest || is_addition) {
            return
          }
          var ctx = chart.ctx
          var y_axis = chart.scales["y"]
          var x_axis = chart.scales["x"]

          var x = get_x_chart(highest['timestamp'] * 1000, x_axis)
          var y = get_y_chart(highest['value'], y_axis)
          var width = 40
          var height = 20
          var rx = Math.min(Math.max(x_axis.left + 10, x - width / 2), x_axis.right - width - 10)
          var ry = y - (height + 10)
          if (y_axis.top <= y && y <= y_axis.bottom) {
            var cx = rx + width / 2
            var cy = ry + height / 2

            ctx.beginPath()
            ctx.moveTo(x, y)
            ctx.lineTo(Math.min(Math.max(x, rx), rx + width - 1), ry + height - 1)
            ctx.lineWidth = 1
            ctx.strokeStyle = 'black'
            ctx.stroke()
            ctx.closePath()

            ctx.fillStyle = '#fff'
            ctx.fillRect(rx, ry, width, height)
            ctx.lineWidth = 1
            ctx.strokeStyle = 'black'
            ctx.strokeRect(rx, ry, width, height)

            ctx.font = '12px Comic Sans MS'
            ctx.textAlign = 'center'
            ctx.fillStyle = 'black'
            ctx.fillText(highest['value'], cx, cy + 4)
          }
        }
      }
    ],
    options: {
      responsive: true,
      interaction: {
          mode: 'nearest',
      },
      scales: {
        x: {
          type: 'time',
          time: {
            unit: get_or_default(resource_info['x_axes_unit'], 'year'),
          },
        },
        y:
          is_addition?
          {
            grid: {
              display: true,
            },
            min: min_field,
            max: max_field,
            afterDataLimits(scale) {
              var range = scale.max - scale.min;
              var grace = range * 0.1;
              scale.max += grace;
              scale.min -= grace;
            }
          }
          :
          {
            grid: {
              display: get_or_default(resource_info['display_y_axis_gridlines'], false),
            },
            min: Math.floor((min_rating - 100) / 100) * 100,
            max: Math.ceil((max_rating + 100) / 100) * 100,
            ticks: {
              stepSize: 50,
              autoSkip: false,
              callback: function(value, index) {
                if (get_or_default(resource_info['without_y_axis_ticks'], false)) {
                  return
                }
                if (y_axis_ticks_every) {
                  return value % y_axis_ticks_every == 0? value : null
                }
                if ((value < max_rating_labels || value % 500) && !rating_labels.has(value)) {
                  return
                }
                return value
              },
            },
          },
      },
      onClick: function (e, items) {
        if (!with_url) {
          return
        }
        for (var i = 0; i < items.length; ++i) {
          var item = items[i]
          rating = e.chart.data.datasets[item.datasetIndex].history[item.index]
          if (rating['url']) {
            url = rating['url']
          } else if (rating['slug'] && rating['cid']) {
            url = '/standings/' + rating['slug'] + '-' + rating['cid'] + '/'
          } else {
            continue
          }
          params = ''
          if (rating['division']) {
              params += '&division=' + rating['division']
          }
          if (rating['sid']) {
              params += '&find_me=' + rating['sid']
          }
          if (params) {
              url += '?' + params.slice(1)
          }
          window.open(url, '_blank')
          break
        }
      },
      onHover: (e, el) => {
        var c = e.target || e.native.target
        c.style.cursor = el[0] && with_url? 'pointer' : 'default'
      },
      plugins: {
        title: {
          display: true,
          text: resource_info['host'] + (is_addition? ' (' + y_field + ')' : ''),
          font: { size: 16 },
        },
        legend: {
          display: resource_info['data'].length > 1,
          position: 'right',
          labels: {
            generateLabels: function() {
              var ci = this.chart
              ret = datasets_labels.map(function(label, index) {
                var hidden = false
                for (var idx = 0; idx < datasets.length; ++idx) {
                  if (ci.data.datasets[idx].label != label) {
                    continue
                  }
                  var meta = ci.getDatasetMeta(idx)
                  hidden = meta.hidden
                  break
                }
                return {
                  text: label,
                  hidden: hidden,
                  fillStyle: datasets_colors[index],
                }
              })
              return ret
            },
          },
          onClick: function(e, item) {
            var ci = this.chart
            var label = item.text[0]
            for (var index = 0; index < datasets.length; ++index) {
              if (ci.data.datasets[index].label != label) {
                continue
              }
              var meta = ci.getDatasetMeta(index)
              meta.hidden = meta.hidden === null? !ci.data.datasets[index].hidden : null
            }
            ci.update()
          },
        },
        tooltip: {
          displayColors: false,
          bodyFont: { size: 14 },
          padding: 6,
          caretPadding: 0,
          caretSize: 0,
          callbacks: {
            title: function(tooltipItems) {
              for (var i = 0; i < tooltipItems.length; ++i) {
                var tooltipItem = tooltipItems[i]
                var dataset = tooltipItem.dataset
                if (dataset.history === undefined) {
                  continue
                }
                var hist = dataset.history[tooltipItem.dataIndex]
                var ret = '<div style="font-weight: bold">' + hist['name'] + '</div>'
                if (resource_info['data'].length > 1) {
                  ret = '<div style="font-weight: bold">' + datasets_labels[dataset.labelIndex_] + '</div>' + ret
                }
                if (is_addition) {
                  ret = '<div style="font-weight: bold">' + y_field + ' = ' + hist['values'][y_field] + '</div>' + ret
                }
                return ret
              }
            },
            label: function(tooltipItem, data) {
              var dataset = tooltipItem.dataset
              if (dataset.history === undefined) {
                return
              }
              var color = dataset.pointBackgroundColor[tooltipItem.dataIndex]
              var hist = dataset.history[tooltipItem.dataIndex]
              var rating = '<span style="font-weight: bold; color: ' + color + '">' + hist['new_rating'] + '</span>'
              if (hist['old_rating'] || hist['rating_change']) {
                var change = hist['old_rating']? hist['new_rating'] - hist['old_rating'] : hist['rating_change']
                if (change > 0) {
                  rating += ' <span style="font-weight: bold; color: #0f0"><i class="fas fa-angle-up"></i>' + change + '</span>'
                } else if (change < 0) {
                  rating += ' <span style="font-weight: bold; color: #f00"><i class="fas fa-angle-down"></i>' + -change + '</span>'
                } else {
                  rating += ' <span style="font-weight: bold; color: #fff">=' + change + '</span>'
                }
              }
              var label = ''
              label += '<div>' + hist['when'] + '</div>'
              label += '<div>' + rating + '</div>'
              if (hist['place']) {
                label += '<div class="small">Rank: ' + hist['place']
                if (hist['total']) {
                  label += ' of ' + hist['total']
                }
                label += '</div>'
              }
              if (typeof hist['score'] != 'undefined') {
                label += '<div class="small">Score: ' + hist['score'] + '</div>'
              }
              if (hist['solved'] != null) {
                label += '<div class="small">Solved: ' + hist['solved'] + ' of ' + hist['n_problems'] + '</div>'
              }
              return label
            },
          },

          enabled: false,

          external: function(context) {
            // Tooltip Element
            var tooltipEl = document.getElementById('chartjs-tooltip')

            // Create element on first render
            if (!tooltipEl) {
                tooltipEl = document.createElement('div')
                tooltipEl.id = 'chartjs-tooltip'
                tooltipEl.innerHTML = '<table></table>'
                document.body.appendChild(tooltipEl)
            }

            // Hide if no tooltip
            var tooltipModel = context.tooltip
            if (tooltipModel.opacity === 0) {
                tooltipEl.style.opacity = 0
                return
            }

            // Set caret Position
            tooltipEl.classList.remove('above', 'below', 'no-transform')
            if (tooltipModel.yAlign) {
                tooltipEl.classList.add(tooltipModel.yAlign)
            } else {
                tooltipEl.classList.add('no-transform')
            }

            function getBody(bodyItem) {
                return bodyItem.lines
            }

            // Set Text
            if (tooltipModel.body) {
                var titleLines = tooltipModel.title || []
                var bodyLines = tooltipModel.body.map(getBody)

                var innerHtml = '<thead>'

                titleLines.forEach(function(title) {
                    innerHtml += '<tr><th>' + title + '</th></tr>'
                })
                innerHtml += '</thead><tbody>'

                bodyLines.forEach(function(body, i) {
                    var colors = tooltipModel.labelColors[i]
                    var style = 'background:' + colors.backgroundColor
                    style += '; border-color:' + colors.borderColor
                    style += '; border-width: 2px'
                    var span = '<span style="' + style + '"></span>'
                    innerHtml += '<tr><td>' + span + body + '</td></tr>'
                })
                innerHtml += '</tbody>'

                var tableRoot = tooltipEl.querySelector('table')
                tableRoot.innerHTML = innerHtml
            }

            var position = context.chart.canvas.getBoundingClientRect()
            var bodyFont = Chart.helpers.toFont(context.chart.config._config.options.plugins.tooltip.bodyFont)

            // Display, position, and set styles for font
            tooltipEl.style.opacity = 1
            tooltipEl.style.position = 'absolute'
            tooltipEl.style.font = bodyFont.string
            var padding = context.chart.config._config.options.plugins.tooltip.padding
            tooltipEl.style.padding = padding + 'px ' + padding + 'px'
            tooltipEl.style.pointerEvents = 'none'
            var left = position.left + window.pageXOffset + tooltipModel.caretX + (tooltipModel.caretX < position.width - tooltipEl.offsetWidth - 10? 0 : -tooltipEl.offsetWidth)
            tooltipEl.style.left = left + 'px'
            var top = position.top + window.pageYOffset + tooltipModel.caretY + (tooltipModel.caretY < position.height - tooltipEl.offsetHeight - 10? 0 : -tooltipEl.offsetHeight)
            tooltipEl.style.top = top + 'px'
          },
        },
      },
    },
  }
}

function add_selection_chart_range(canvas_selector, chart, with_close_chart=false) {
  $('#' + canvas_selector).data('chart', chart)

  var overlay = document.createElement('canvas');
  overlay.setAttribute('id', canvas_selector + '_overlay');
  overlay.setAttribute('class', 'resource_rating_overlay');

  var show_hint = document.createElement('div');
  show_hint.setAttribute('class', 'resource_rating_hint small text-muted invisible');
  show_hint.textContent = '*double click to previous zoom';

  var canvas = document.getElementById(canvas_selector);

  canvas.parentNode.insertBefore(show_hint, canvas);
  if (with_close_chart) {
    var close_chart = document.createElement('div');
    close_chart.setAttribute('class', 'resource_rating_close');
    var i = document.createElement('i');
    i.setAttribute('class', 'fas fa-times'); close_chart.appendChild(i);
    canvas.parentNode.insertBefore(close_chart, canvas);
    close_chart.addEventListener('click', () => { canvas.parentNode.remove() });
  }
  canvas.parentNode.insertBefore(overlay, canvas);

  var selectionContext;

  function change_chart_size(chart, size) {
    overlay.width = size.width;
    overlay.height = size.height;
    selectionContext = overlay.getContext('2d');
    selectionContext.globalAlpha = 0.3;
  }

  chart.options.onResize = change_chart_size;
  change_chart_size(chart, chart)

  var selectionRect = {
    startX: 0,
    startY: 0,
    endX: 0,
    endY: 0,
  };
  var dragX = false;
  var dragY = false;
  var draged = false;
  const stack_axes = [];
  const dragBorder = 30;

  canvas.addEventListener('pointerdown', evt => {
    const rect = canvas.getBoundingClientRect();
    const x = evt.clientX - rect.left;
    const y = evt.clientY - rect.top;
    selectionRect.startX = Math.max(Math.min(x, chart.chartArea.right), chart.chartArea.left);
    selectionRect.startY = Math.max(Math.min(y, chart.chartArea.bottom), chart.chartArea.top);
    selectionRect.endX = selectionRect.startX;
    selectionRect.endY = selectionRect.startY;
    draged = false;
    dragX = true;
    dragY = true;
  });

  function clear_overlay() {
    $('.resource_rating_overlay').map((idx, overlay) => {
      overlay.getContext('2d').clearRect(0, 0, overlay.width, overlay.height);
    })
  }

  function update_chart_range(evt) {
    const rect = canvas.getBoundingClientRect();
    const x = evt.clientX - rect.left;
    const y = evt.clientY - rect.top;
    clear_overlay();
    if (dragX || dragY) {
      selectionRect.endX = Math.max(Math.min(x, chart.chartArea.right), chart.chartArea.left);
      selectionRect.endY = Math.max(Math.min(y, chart.chartArea.bottom), chart.chartArea.top);
      const w = selectionRect.endX - selectionRect.startX;
      const h = selectionRect.endY - selectionRect.startY;
      if (dragX && dragY) {
        if (Math.abs(w) > 10) {
          dragY = false;
        } else if (Math.abs(h) > 10) {
          dragX = false;
        }
      } else {
        if (dragX) {
          selectionContext.fillRect(selectionRect.startX, chart.chartArea.top, w, chart.chartArea.height);
        } else if (dragY) {
          selectionContext.fillRect(chart.chartArea.left, selectionRect.startY, chart.chartArea.width, h);
        }
        draged = true;
      }
    } else {
      const clip_x = Math.max(Math.min(x, chart.chartArea.right), chart.chartArea.left);
      const clip_y = Math.max(Math.min(y, chart.chartArea.bottom), chart.chartArea.top);
      if (x < chart.chartArea.left + dragBorder || chart.chartArea.right - dragBorder < x) {
        selectionContext.fillRect(chart.chartArea.left, clip_y, chart.chartArea.width, 1);
      } else if (y < chart.chartArea.top + dragBorder || chart.chartArea.bottom - dragBorder < y) {

        const x_axis = chart.scales['x'];
        const value = (clip_x - x_axis.left) / x_axis.width * (x_axis.max - x_axis.min) + x_axis.min;

        $('.resource_rating_overlay').map((idx, overlay) => {
          const canvas = overlay.nextSibling;
          const chart = $(canvas).data('chart');
          const x_axis = chart.scales['x'];
          if (x_axis.min < value && value < x_axis.max) {
            const x = (value - x_axis.min) / (x_axis.max - x_axis.min) * x_axis.width + x_axis.left;
            overlay.getContext('2d').fillRect(x, chart.chartArea.top, 1, chart.chartArea.height);
          }
        });
      }
    }
  }

  canvas.addEventListener('pointermove', update_chart_range);

  canvas.addEventListener('dblclick', evt => {
    evt.preventDefault();
    if (stack_axes.length) {
      [x_min, x_max, y_min, y_max] = stack_axes.pop();
      chart.options.scales.x.min = x_min;
      chart.options.scales.x.max = x_max;
      chart.options.scales.y.min = y_min;
      chart.options.scales.y.max = y_max;
      chart.update();
      if (!stack_axes.length) {
        show_hint.classList.add('invisible');
      }
    }
    return false;
  });

  function set_chart_range(evt) {
    update_chart_range(evt);
    clear_overlay();
    if (draged) {
      stack_axes.push([chart.options.scales.x.min, chart.options.scales.x.max, chart.options.scales.y.min, chart.options.scales.y.max]);
      show_hint.classList.remove('invisible');
    }
    if (dragX && draged) {
      const x_axis = chart.scales['x'];
      const start_value = (selectionRect.startX - x_axis.left) / x_axis.width * (x_axis.max - x_axis.min) + x_axis.min;
      const end_value = (selectionRect.endX - x_axis.left) / x_axis.width * (x_axis.max - x_axis.min) + x_axis.min;
      chart.options.scales.x.min = Math.min(start_value, end_value);
      chart.options.scales.x.max = Math.max(start_value, end_value);
      chart.update();
    } else if (dragY && draged) {
      const y_axis = chart.scales['y'];
      const start_value = (selectionRect.startY - y_axis.top) / y_axis.height * (y_axis.min - y_axis.max) + y_axis.max;
      const end_value = (selectionRect.endY - y_axis.top) / y_axis.height * (y_axis.min - y_axis.max) + y_axis.max;
      chart.options.scales.y.min = Math.min(start_value, end_value);
      chart.options.scales.y.max = Math.max(start_value, end_value);
      chart.update();
    }
    dragX = false;
    dragY = false;
    draged = false;
  }
  canvas.addEventListener('pointerup', evt => { set_chart_range(evt); });
  canvas.addEventListener('pointerout', evt => { set_chart_range(evt); });
}

function add_selection_chart_fields(resource_info, resource_rating_id, resource_fields_id, resource_dates) {
  var resource_fields = $('#' + resource_fields_id)
  if (resource_info['fields'] && resource_info['fields'].length) {
    resource_fields.parent().removeClass('invisible')
    resource_fields.select2({
      data: resource_info['fields'],
      theme: 'bootstrap',
      placeholder: 'Select field',
      dropdownAutoWidth : true,
    })
  } else {
    resource_fields.parent().remove()
  }

  resource_fields.on('change', (function(e) {
    var resource_info = this
    var resource_fields = $('#' + resource_fields_id)
    var field = resource_fields.val()
    if (!field) {
      return;
    }
    resource_fields.val(null).trigger('change')
    var resource_rating = $('#' + resource_rating_id)
    var new_resource_rating_id = resource_rating_id + '_' + field
    $('#' + new_resource_rating_id).remove()
    var div = $('<div></div>');
    div.append('<canvas id="' + new_resource_rating_id + '" height="75vh"></canvas>');
    resource_rating.after(div);

    config = create_chart_config(resource_info, resource_dates, y_field=field, is_addition=true)
    if (config === false) {
      $('#' + new_resource_rating_id).parent().remove()
    } else {
      var ctx = new Chart(new_resource_rating_id, config)
      add_selection_chart_range(new_resource_rating_id, ctx, with_close_chart=true)
    }
  }).bind(resource_info))
}
