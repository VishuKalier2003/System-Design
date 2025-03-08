
## Strategy Pattern: Overview

**Definition & Purpose:**
The **Strategy pattern** defines a family of algorithms, encapsulates each one, and makes them interchangeable. It allows the algorithm to vary independently from the clients that use it. In other words, you can choose a different algorithm (or strategy) at runtime without changing the code that uses it.

**Why & Where in System Design and Microservices:**
- **System Design:**
  - **Flexibility:** The pattern lets you switch between different algorithms (or business rules) based on runtime parameters.
  - **Decoupling:** It separates the decision-making logic from the execution, reducing dependencies between components.
  - **Scalability:** In distributed systems, different strategies can be deployed or scaled independently.

- **Microservices:**
  - **Dynamic Behavior:** For example, a routing service might select different algorithms (e.g., heap-based versus sorting-based) based on load, data size, or configuration.
  - **Spring Boot Integration:** Spring Boot can manage strategy instances as singleton beans using annotations like `@Component` and `@Qualifier`. This simplifies dependency injection and makes it easy to switch strategies without changing your business logic.
  - **Real-World Use Cases:** Payment processing, request routing, discount calculations, or load balancing are common scenarios where strategy selection based on conditions (like active users, ports, or external configurations) is essential.

---

## Detailed Explanation of the Provided Java Code

The code below is organized into several files. **Do not change the code or its comments.** I have added extra inline comments (prefixed with `// >>`) for additional clarity.

### **Strategy.java**
```java
package Strategy;

// Imp- The function or class that will be dynamically altered
public interface Strategy {
    public int maxElement(int nums[]);
    // >> This interface defines the contract: given an array of integers,
    // >> return the maximum element using a specific algorithm.
}
```

### **RoutingType.java**
```java
package Strategy;

// Imp - Enum to store the predefined Routings (heaps / arrays)
public enum RoutingType {
    HEAPIFY, SORTING
    // >> This enum defines the types of strategies available.
    // >> HEAPIFY represents using a heap-based approach.
    // >> SORTING represents using an array sorting approach.
}
```

### **SortingStrategy.java**
```java
package Strategy;

import java.util.Arrays;

// Imp- It is generally a singleton instance hence we use @Component
public class SortingStrategy implements Strategy {
    // All the objects or data will pass through one pipe or instance
    @Override
    public int maxElement(int nums[]) {
        System.out.println("Array sorting technique");
        // >> This strategy sorts the array and returns the last element,
        // >> which is the maximum value after sorting.
        Arrays.sort(nums);
        return nums[nums.length-1];
    }
}
```

### **HeapStrategy.java**
```java
package Strategy;

import java.util.Collections;
import java.util.PriorityQueue;

// Imp- It is generally a singleton instance hence we use @Component
public class HeapStrategy implements Strategy {
    // All the objects or data will pass through one pipe or instance
    @Override
    public int maxElement(int nums[]) {
        System.out.println("Performing Heap operation");
        // >> This strategy uses a PriorityQueue (max-heap) to find the maximum.
        PriorityQueue<Integer> maxHeap = new PriorityQueue<>(Collections.reverseOrder());
        for (int num : nums)
            maxHeap.add(num);
        return maxHeap.peek();
    }
}
```

### **StrategyRouting.java**
```java
package Strategy;

import java.util.HashMap;
import java.util.Map;

public class StrategyRouting {
    private final Strategy heapStrategy;
    private final Strategy sortingStrategy;

    public final Map<RoutingType, Strategy> strategyMap = new HashMap<>();

    // Imp- Use @Qualifier annotation to direct the beans
    public StrategyRouting(Strategy heapStrategy, Strategy sortingStrategy) {
        this.heapStrategy = heapStrategy;       // Use @Qualifier("component-name-1")
        this.sortingStrategy = sortingStrategy;   // Use @Qualifier("component-name-2")
        // Imp- Map used to store and direct the control to the specific strategy instances
        strategyMap.put(RoutingType.HEAPIFY, this.heapStrategy);
        strategyMap.put(RoutingType.SORTING, this.sortingStrategy);
    }

    public int evaluateStrategy(int nums[], String type) {
        // >> Converts the passed string to the corresponding RoutingType enum.
        Strategy strategy = strategyMap.get(RoutingType.valueOf(type.toUpperCase()));
        if (strategy == null)
            throw new IllegalArgumentException("Wrong type entered");
        // >> Delegates the operation to the chosen strategy's implementation.
        return strategy.maxElement(nums);
    }
}
```

### **TestStrategy.java**
```java
package Strategy;

import Reader.FastReader;

public class TestStrategy {     // Class to test the desired code
    public static void main(String[] args) {
        FastReader fastReader = new FastReader();
        int nums[] = new int[5];
        for (int i = 0; i < nums.length; i++)
            nums[i] = fastReader.nextInt();
        // Creating the strategy object and defining the available strategies
        StrategyRouting strategyRouting = new StrategyRouting(new HeapStrategy(), new SortingStrategy());
        // For now the strategy selection is at run-time but can be automated by evaluating parameters like port no, active users, etc.
        System.out.println(strategyRouting.evaluateStrategy(nums, "Heapify"));      // strategy selection as Heap
        System.out.println(strategyRouting.evaluateStrategy(nums, "sorting"));        // strategy selection as Sorting
    }
}
```

**Explanation Summary:**
- The **`Strategy` interface** defines a single method to compute the maximum element from an integer array.
- **`RoutingType`** enumerates the available strategies.
- **`SortingStrategy`** and **`HeapStrategy`** are two different implementations that use different algorithms.
- **`StrategyRouting`** holds a map of these strategies, allowing the client to choose one at runtime based on a string input.
- **`TestStrategy`** demonstrates how to read input and execute the strategies.

---

## A More Complex Example: Payment Processing Strategy in Spring Boot

Imagine a microservice that processes payments and needs to choose a different strategy based on the payment method (e.g., Credit Card, PayPal, or Bitcoin). In a Spring Boot application, you can leverage dependency injection, along with `@Component` and `@Qualifier` annotations, to implement this pattern.

### **PaymentStrategy.java**
```java
package com.example.payment;

public interface PaymentStrategy {
    // Process payment and return a status code (e.g., 200 for success)
    int processPayment(double amount);
}
```

### **CreditCardPaymentStrategy.java**
```java
package com.example.payment;

import org.springframework.stereotype.Component;

@Component("creditCardStrategy")
public class CreditCardPaymentStrategy implements PaymentStrategy {
    @Override
    public int processPayment(double amount) {
        System.out.println("Processing Credit Card Payment of $" + amount);
        // Implement credit card payment logic here
        return 200; // success code
    }
}
```

### **PaypalPaymentStrategy.java**
```java
package com.example.payment;

import org.springframework.stereotype.Component;

@Component("paypalStrategy")
public class PaypalPaymentStrategy implements PaymentStrategy {
    @Override
    public int processPayment(double amount) {
        System.out.println("Processing PayPal Payment of $" + amount);
        // Implement PayPal payment logic here
        return 200; // success code
    }
}
```

### **PaymentContext.java**
```java
package com.example.payment;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.Map;

@Component
public class PaymentContext {
    // Map to store available strategies
    private final Map<String, PaymentStrategy> strategyMap = new HashMap<>();

    // Constructor injection with Qualifiers to choose the correct beans
    @Autowired
    public PaymentContext(@Qualifier("creditCardStrategy") PaymentStrategy creditCardStrategy,
                          @Qualifier("paypalStrategy") PaymentStrategy paypalStrategy) {
        // You could add more strategies here as needed
        strategyMap.put("CREDIT_CARD", creditCardStrategy);
        strategyMap.put("PAYPAL", paypalStrategy);
    }

    public int executePayment(String paymentType, double amount) {
        PaymentStrategy strategy = strategyMap.get(paymentType.toUpperCase());
        if (strategy == null) {
            throw new IllegalArgumentException("Unsupported payment type: " + paymentType);
        }
        return strategy.processPayment(amount);
    }
}
```

### **PaymentController.java**
```java
package com.example.payment;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/payment")
public class PaymentController {

    @Autowired
    private PaymentContext paymentContext;

    // Endpoint to process payment
    @PostMapping("/process")
    public String processPayment(@RequestParam String type, @RequestParam double amount) {
        int status = paymentContext.executePayment(type, amount);
        return status == 200 ? "Payment processed successfully" : "Payment failed";
    }
}
```

**Key Annotations & Integration:**
- **`@Component`** is used to mark each strategy as a Spring bean, ensuring singleton behavior.
- **`@Qualifier`** helps in disambiguating multiple beans of the same type when injecting dependencies.
- **`@Autowired`** is used for dependency injection into the context and controllers.
- **`@RestController`** and **`@RequestMapping`** integrate this strategy into a RESTful microservice.

**Why and When to Use in Microservices:**
- **Dynamic Selection:** Based on runtime parameters (e.g., payment method), different algorithms are selected.
- **Decoupling:** Payment processing logic is decoupled from the controller, making the system modular and easier to extend.
- **Testability:** Each strategy can be unit-tested independently.
- **Scalability:** You can add or update payment methods without affecting the overall architecture.

---

## Summary

The **Strategy pattern** is invaluable when you need to vary an algorithm at runtime without coupling the algorithm’s implementation to its usage. In system design and microservices, it provides flexibility, modularity, and easier maintenance. Using Spring Boot annotations like `@Component`, `@Autowired`, and `@Qualifier` further simplifies the implementation by leveraging Spring’s dependency injection framework.
