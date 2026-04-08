package com.example.service;

import java.util.List;
import com.example.model.Order;
import com.example.model.Customer;
import com.example.dao.OrderDao;

public class OrderService extends BaseService implements Processable {
    private OrderDao orderDao;
    private List<String> auditLog;

    public OrderService(OrderDao orderDao) {
        this.orderDao = orderDao;
    }

    public Order process(Order order) {
        if (order == null) {
            throw new IllegalArgumentException("Order must not be null");
        }
        logInfo("Processing order: " + order.getId());
        order.setStatus("PROCESSED");
        return orderDao.save(order);
    }

    public Order findOrder(String id) {
        return orderDao.findById(id);
    }

    public double calculateTotal(List<Order> orders) {
        double total = 0;
        for (Order o : orders) {
            total += o.getAmount();
        }
        return total;
    }
}
