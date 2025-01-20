from rest_framework import viewsets,status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from .models import Category, Product, Order, OrderItem
from .serializers import (
    CategorySerializer, ProductSerializer,
    OrderSerializer, OrderItemSerializer
)
from decimal import Decimal
from rest_framework.response import Response

class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]

class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = Product.objects.all()
        category = self.request.query_params.get('category', None)
        if category:
            queryset = queryset.filter(category_id=category)
        return queryset

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        items_data = request.data.get('items', [])
        if not items_data:
            return Response(
                {'error': 'No items provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Calculate total amount and validate stock before creating order
        total_amount = Decimal('0.00')
        products_to_update = []

        # First pass: validate all products and calculate total
        for item_data in items_data:
            try:
                product = Product.objects.select_for_update().get(
                    id=item_data['product']
                )
                quantity = int(item_data['quantity'])

                if quantity <= 0:
                    return Response(
                        {'error': f'Invalid quantity for product {product.name}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                if product.stock < quantity:
                    return Response(
                        {'error': f'Insufficient stock for {product.name}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                item_total = product.price * quantity
                total_amount += item_total
                products_to_update.append((product, quantity))

            except Product.DoesNotExist:
                return Response(
                    {'error': f'Product {item_data["product"]} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )
            except (KeyError, ValueError):
                return Response(
                    {'error': 'Invalid item data format'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # Create order with calculated total
        order = Order.objects.create(
            user=request.user,
            total_amount=total_amount,
            status='PENDING'
        )

        # Create order items and update stock
        for product, quantity in products_to_update:
            OrderItem.objects.create(
                order=order,
                product=product,
                quantity=quantity,
                price_at_time=product.price
            )
            product.stock -= quantity
            product.save()

        serializer = self.get_serializer(order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()
        
        # Only allow updating the status
        if not partial:
            return Response(
                {'error': 'Only PATCH method is allowed for updating orders'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(instance, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        
        # Only allow status updates
        if set(request.data.keys()) - {'status'}:
            return Response(
                {'error': 'Only status can be updated'},
                status=status.HTTP_400_BAD_REQUEST
            )

        self.perform_update(serializer)
        return Response(serializer.data)