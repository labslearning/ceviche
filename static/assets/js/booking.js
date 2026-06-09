/**
 * 🎫 Booking Engine - Ceviche Platform (Pro Version)
 * Gestiona la selección de sillas, cálculo de precios y validación visual.
 */

$(document).ready(function() {
    // 1. CONFIGURACIÓN DINÁMICA
    const $mapContainer = $('#seating-map-container'); 
    const FUNCTION_ID = $mapContainer.data('function-id'); 

    // Validación defensiva
    if (!FUNCTION_ID) {
        console.warn("⚠️ [Booking] Faltan datos de configuración (data-function-id).");
        return;
    }

    const API_URL = `/api/v1/functions/${FUNCTION_ID}/seats/`;

    // 2. ESTADO DEL CARRITO (State Management)
    const cartState = {
        selectedIds: new Set(),
        total: 0
    };

    // Formateador de dinero (COP)
    const currencyFormatter = new Intl.NumberFormat('es-CO', {
        style: 'currency',
        currency: 'COP',
        minimumFractionDigits: 0
    });

    // Constantes de Estilo
    const STYLES = {
        AVAILABLE: { fill: '#28a745', cursor: 'pointer', opacity: '1' }, 
        SOLD:      { fill: '#dc3545', cursor: 'not-allowed', opacity: '0.6' },
        SELECTED:  { fill: '#007bff', cursor: 'pointer', opacity: '1' },
        LOCKED:    { fill: '#ffc107', cursor: 'wait', opacity: '0.8' }
    };

    console.log(`🚀 Iniciando motor de reservas para Función: ${FUNCTION_ID}`);

    // 3. CARGA DE DATOS
    function loadSeats() {
        $.ajax({
            url: API_URL,
            method: 'GET',
            success: function(seats) {
                renderMap(seats);
            },
            error: function(jqXHR) {
                console.error("❌ Error cargando sillas:", jqXHR);
            }
        });
    }

    // 4. RENDERIZADO INTELIGENTE
    function renderMap(seats) {
        seats.forEach(seat => {
            const $el = $(`#${seat.svg_id}`);

            if ($el.length) {
                // Inyectamos la data de la BD dentro del elemento DOM
                $el.data('seat-info', seat);
                $el.off('click mouseenter mouseleave'); // Limpieza de eventos

                if (seat.status === 'SOLD') {
                    applyStyle($el, 'SOLD');
                    $el.attr('title', `Silla ${seat.row}-${seat.number} (VENDIDA)`);
                } else {
                    applyStyle($el, 'AVAILABLE');
                    $el.attr('title', `Silla ${seat.row}-${seat.number} - ${currencyFormatter.format(seat.price)}`);
                    
                    $el.on('click', function() {
                        toggleSeatSelection($(this));
                    });
                    
                    // Efectos visuales sutiles
                    $el.on('mouseenter', function() { 
                        if(!cartState.selectedIds.has(seat.id)) $(this).css('opacity', '0.7'); 
                    });
                    $el.on('mouseleave', function() { 
                        if(!cartState.selectedIds.has(seat.id)) $(this).css('opacity', '1'); 
                    });
                }
            }
        });
    }

    // 5. LÓGICA DE SELECCIÓN (CORE)
    function toggleSeatSelection($el) {
        const seat = $el.data('seat-info');
        
        if (!seat || !seat.price) return;

        if (cartState.selectedIds.has(seat.id)) {
            // DESELECCIONAR
            cartState.selectedIds.delete(seat.id);
            cartState.total -= parseFloat(seat.price);
            applyStyle($el, 'AVAILABLE');
            removeCartItemVisual(seat.id);
        } else {
            // SELECCIONAR
            if (cartState.selectedIds.size >= 6) {
                alert("Solo puedes comprar máximo 6 boletas por transacción.");
                return;
            }
            cartState.selectedIds.add(seat.id);
            cartState.total += parseFloat(seat.price);
            applyStyle($el, 'SELECTED');
            addCartItemVisual(seat);
        }
        updateCheckoutUI();
    }

    // 6. ACTUALIZACIÓN UI
    function addCartItemVisual(seat) {
        const itemHtml = `
            <li id="cart-item-${seat.id}" class="list-group-item d-flex justify-content-between lh-condensed" style="margin-bottom: 5px; background: #f8f9fa;">
                <div>
                    <h6 class="my-0">Fila ${seat.row} - Asiento ${seat.number}</h6>
                    <small class="text-muted">${seat.category_name}</small>
                </div>
                <span class="text-muted">${currencyFormatter.format(seat.price)}</span>
            </li>
        `;
        $('#cart-items-list').append(itemHtml);
    }

    function removeCartItemVisual(id) {
        $(`#cart-item-${id}`).fadeOut(200, function() { $(this).remove(); });
    }

    function updateCheckoutUI() {
        $('#cart-total-amount').text(currencyFormatter.format(cartState.total));
        $('#hidden-selected-seats').val(Array.from(cartState.selectedIds).join(','));

        const $btn = $('#btn-checkout-action');
        if (cartState.selectedIds.size > 0) {
            $btn.prop('disabled', false).removeClass('disabled');
            $btn.text(`Pagar ${currencyFormatter.format(cartState.total)}`);
        } else {
            $btn.prop('disabled', true).addClass('disabled');
            $btn.text('Selecciona tus sillas');
        }
    }

    function applyStyle($el, styleName) {
        $el.css(STYLES[styleName]);
    }

    loadSeats();
});
